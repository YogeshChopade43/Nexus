import { useState, useCallback } from "react";
import { Plus, Trash2, TestTube, Check, Eye, EyeOff } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "../ui/Card";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";
import { Badge } from "../ui/Badge";
import type { LLMProviderConfig, LLMProviderInfo, LLMProviderFormData } from "../../types/llm";

interface LLMSettingsProps {
  configs: LLMProviderConfig[];
  providerInfo: LLMProviderInfo[];
  loading: boolean;
  onCreate: (data: LLMProviderFormData) => Promise<LLMProviderConfig | null>;
  onUpdate: (id: number, data: Partial<LLMProviderFormData>) => Promise<boolean>;
  onDelete: (id: number) => Promise<boolean>;
  onRefresh: () => void;
  testChat: (providerId: number, message: string) => Promise<{ content: string | null; error: string | null }>;
}

/** A provider's monogram tile (no third-party logos to keep in sync). */
function ProviderMark({ name }: { name: string }) {
  return (
    <span aria-hidden className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-nexus-border bg-nexus-bg-tertiary text-sm font-semibold uppercase text-nexus-text-secondary">
      {name.slice(0, 2)}
    </span>
  );
}

export function LLMSettings({
  configs,
  providerInfo,
  loading,
  onCreate,
  onUpdate,
  onDelete,
  testChat,
}: LLMSettingsProps) {
  const [showForm, setShowForm] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState<string>("");
  const [formModel, setFormModel] = useState("");
  const [formApiKey, setFormApiKey] = useState("");
  const [formBaseUrl, setFormBaseUrl] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [testing, setTesting] = useState<number | null>(null);
  const [testResult, setTestResult] = useState<Record<number, { content: string | null; error: string | null }>>({});

  const selectedProviderInfo = providerInfo.find(p => p.name === selectedProvider);

  const getProviderLabel = (name: string) => providerInfo.find(p => p.name === name)?.label || name;

  const handleCreate = useCallback(async () => {
    if (!selectedProvider) return null;
    const data: LLMProviderFormData = {
      provider_name: selectedProvider as LLMProviderFormData["provider_name"],
      model: formModel,
      api_key: formApiKey || undefined,
      base_url: formBaseUrl || undefined,
      enabled: true,
    };
    const result = await onCreate(data);
    if (result) {
      setSelectedProvider("");
      setFormModel("");
      setFormApiKey("");
      setFormBaseUrl("");
      setShowForm(false);
    }
    return result;
  }, [selectedProvider, formModel, formApiKey, formBaseUrl, onCreate]);

  const handleTest = useCallback(async (config: LLMProviderConfig) => {
    setTesting(config.id);
    try {
      const result = await testChat(config.id, "Say hello in one sentence");
      setTestResult(prev => ({ ...prev, [config.id]: result }));
    } catch {
      setTestResult(prev => ({ ...prev, [config.id]: { content: null, error: "Test failed" } }));
    } finally {
      setTesting(null);
    }
  }, [testChat]);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold text-nexus-text">AI providers</h2>
          <p className="mt-0.5 text-[13px] text-nexus-text-secondary">
            The models Nexus thinks with: OpenAI, Anthropic, OpenRouter, Groq, Grok, or Ollama on your own machine.
          </p>
        </div>
        <Button size="sm" onClick={() => setShowForm(!showForm)}>
          <Plus className="w-3.5 h-3.5" />
          Add Provider
        </Button>
      </div>

      {showForm && (
        <Card>
          <CardHeader>
            <CardTitle>Add LLM Provider</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4">
              <div>
                <label className="block text-sm font-medium text-nexus-text mb-2">Provider</label>
                <select
                  value={selectedProvider}
                  onChange={e => {
                    const providerName = e.target.value;
                    setSelectedProvider(providerName);
                    const info = providerInfo.find(p => p.name === providerName);
                    setFormModel(info?.models[0] || "");
                  }}
                  className="w-full px-3 py-2 rounded-lg bg-nexus-bg-secondary border border-nexus-border text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent/25 focus:border-nexus-accent"
                >
                  <option value="">Select a provider...</option>
                  {providerInfo.map(p => (
                    <option key={p.name} value={p.name}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-nexus-text mb-2">Model</label>
                {/* Free text with suggestions: local and routed providers use model names we can't list. */}
                <input
                  list="llm-model-suggestions"
                  value={formModel}
                  onChange={e => setFormModel(e.target.value)}
                  disabled={!selectedProvider}
                  placeholder="Model name"
                  className="w-full px-3 py-2 rounded-lg bg-nexus-bg-secondary border border-nexus-border text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent/25 focus:border-nexus-accent disabled:opacity-50 disabled:cursor-not-allowed"
                />
                <datalist id="llm-model-suggestions">
                  {(selectedProviderInfo?.models || []).map(m => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
              </div>

              <div className="relative">
                <Input
                  label="API Key"
                  type={showApiKey ? "text" : "password"}
                  value={formApiKey}
                  onChange={e => setFormApiKey(e.target.value)}
                  placeholder="Enter API key (if required)"
                />
                <button
                  type="button"
                  onClick={() => setShowApiKey(!showApiKey)}
                  className="absolute right-3 top-[28px] text-nexus-text-muted hover:text-nexus-text transition-colors"
                  tabIndex={-1}
                  aria-label={showApiKey ? "Hide API key" : "Show API key"}
                >
                  {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>

              <Input
                label="Base URL"
                value={formBaseUrl}
                onChange={e => setFormBaseUrl(e.target.value)}
                placeholder="https://api.example.com (optional)"
              />
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setShowForm(false)}>
                Cancel
              </Button>
              <Button onClick={handleCreate} disabled={!selectedProvider || !formModel.trim()}>Add Provider</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <div className="animate-spin w-8 h-8 border-2 border-nexus-accent border-t-transparent rounded-full" />
        </div>
      ) : configs.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-nexus-text-muted">
            <p>No LLM providers configured yet.</p>
            <p className="text-xs mt-2">Add a provider above to get started.</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {configs.map(config => (
            <div key={config.id} className="rounded-lg border border-nexus-border bg-nexus-bg-secondary p-4 shadow-surface">
              <div className="flex items-start gap-3">
                <ProviderMark name={config.provider_name} />
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-nexus-text">{getProviderLabel(config.provider_name)}</span>
                    <Badge variant={config.enabled ? "success" : "default"} size="sm">
                      {config.enabled ? "Active" : "Disabled"}
                    </Badge>
                  </div>
                  <p className="text-sm text-nexus-text-muted">Model: {config.model}</p>
                  {config.base_url && <p className="text-xs text-nexus-text-muted">{config.base_url}</p>}

                  <div className="mt-3 flex items-center gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      className="gap-1.5"
                      onClick={() => handleTest(config)}
                      disabled={testing === config.id}
                    >
                      {testing === config.id ? (
                        <div className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" />
                      ) : testResult[config.id] !== undefined && testResult[config.id] !== null ? (
                        <>
                          <Check className="w-3 h-3" />
                          {testResult[config.id].error ? "Failed" : "Working"}
                        </>
                      ) : (
                        <>
                          <TestTube className="w-3 h-3" />
                          Test
                        </>
                      )}
                    </Button>
                    <Button variant="secondary" size="sm" onClick={() => void onUpdate(config.id, { enabled: !config.enabled })}>
                      {config.enabled ? "Disable" : "Enable"}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-nexus-danger"
                      aria-label="Delete provider"
                      onClick={() => { if (window.confirm(`Delete ${config.provider_name} · ${config.model}?`)) void onDelete(config.id); }}
                    >
                      <Trash2 className="w-3 h-3" />
                    </Button>
                  </div>

                  {testResult[config.id] !== undefined && (
                    <div className="mt-3 p-2 bg-nexus-bg-secondary border border-nexus-border rounded text-xs text-nexus-text-secondary">
                      {testResult[config.id].error ? (
                        <p className="text-nexus-danger">{testResult[config.id].error}</p>
                      ) : testResult[config.id].content ? (
                        <p>{testResult[config.id].content}</p>
                      ) : (
                        <p className="text-nexus-danger">Test failed</p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
