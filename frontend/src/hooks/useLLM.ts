import { useCallback, useEffect, useSyncExternalStore } from "react";
import { llmService } from "../services/llm";
import { getErrorMessage } from "../lib/utils";
import type {
  LLMProviderConfig,
  LLMProviderInfo,
  LLMProviderFormData,
  LLMChatRequest,
  LLMChatResponse,
} from "../types/llm";

interface UseLLMReturn {
  configs: LLMProviderConfig[];
  providerInfo: LLMProviderInfo[];
  loading: boolean;
  error: Error | null;
  createConfig: (data: LLMProviderFormData) => Promise<LLMProviderConfig | null>;
  updateConfig: (id: number, data: Partial<LLMProviderFormData>) => Promise<boolean>;
  deleteConfig: (id: number) => Promise<boolean>;
  refreshConfigs: () => Promise<void>;
  chat: (req: LLMChatRequest) => Promise<LLMChatResponse | null>;
  testChat: (providerId: number, message: string) => Promise<{ content: string | null; error: string | null }>;
}

interface LLMState {
  configs: LLMProviderConfig[];
  providerInfo: LLMProviderInfo[];
  loading: boolean;
  error: Error | null;
}

// One shared store: the chat panel, settings and workflow editor must agree on which
// providers exist, or a provider deleted in Settings stays selected in the chat.
let state: LLMState = { configs: [], providerInfo: [], loading: false, error: null };
let loaded = false;
const listeners = new Set<() => void>();

function setState(patch: Partial<LLMState>) {
  state = { ...state, ...patch };
  listeners.forEach(listener => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

async function refreshShared(): Promise<void> {
  loaded = true;
  setState({ loading: true, error: null });
  try {
    const [configs, providerInfo] = await Promise.all([llmService.listConfigs(), llmService.listProviders()]);
    setState({ configs, providerInfo, loading: false });
  } catch (err) {
    setState({ loading: false, error: new Error(getErrorMessage(err)) });
  }
}

export function useLLM(): UseLLMReturn {
  const { configs, providerInfo, loading, error } = useSyncExternalStore(subscribe, () => state);
  const setError = useCallback((err: Error) => setState({ error: err }), []);
  const refreshConfigs = useCallback(() => refreshShared(), []);

  useEffect(() => {
    if (!loaded) void refreshShared();
  }, []);

  const createConfig = useCallback(
    async (data: LLMProviderFormData): Promise<LLMProviderConfig | null> => {
      try {
        const config = await llmService.createConfig(data);
        await refreshConfigs();
        return config;
      } catch (err) {
        setError(new Error(getErrorMessage(err)));
        return null;
      }
    },
    [refreshConfigs]
  );

  const updateConfig = useCallback(
    async (id: number, data: Partial<LLMProviderFormData>): Promise<boolean> => {
      try {
        await llmService.updateConfig(id, data);
        await refreshConfigs();
        return true;
      } catch (err) {
        setError(new Error(getErrorMessage(err)));
        return false;
      }
    },
    [refreshConfigs]
  );

  const deleteConfig = useCallback(
    async (id: number): Promise<boolean> => {
      try {
        await llmService.deleteConfig(id);
        await refreshConfigs();
        return true;
      } catch (err) {
        setError(new Error(getErrorMessage(err)));
        return false;
      }
    },
    [refreshConfigs]
  );

  const chat = useCallback(async (req: LLMChatRequest): Promise<LLMChatResponse | null> => {
    try {
      return await llmService.chat(req);
    } catch (err) {
      setError(new Error(getErrorMessage(err)));
      return null;
    }
  }, []);

  const testChat = useCallback(
    async (providerId: number, message: string): Promise<{ content: string | null; error: string | null }> => {
      try {
        const result = await llmService.chat({
          messages: [{ role: "user", content: message }],
          provider_id: providerId,
        });
        return { content: result?.content ?? null, error: null };
      } catch (err) {
        return { content: null, error: getErrorMessage(err) };
      }
    },
    []
  );

  return {
    configs,
    providerInfo,
    loading,
    error,
    createConfig,
    updateConfig,
    deleteConfig,
    refreshConfigs,
    chat,
    testChat,
  };
}
