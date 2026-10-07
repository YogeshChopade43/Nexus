import { useEffect, useState } from 'react';
import { cn } from '../lib/utils';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { Separator } from '../components/ui/Separator';
import { Badge } from '../components/ui/Badge';
import { User, Moon, Sun, Monitor, Cpu } from 'lucide-react';
import { useSettings } from '../hooks/useSettings';
import { useLLM } from '../hooks/useLLM';
import { LLMSettings } from '../components/llm/LLMSettings';
import { settingsService } from '../services/settings';

const tabs = [
  { id: 'general', label: 'General', icon: User },
  { id: 'ai', label: 'AI', icon: Cpu },
] as const;

type TabId = typeof tabs[number]['id'];

const THEMES = [
  { id: 'dark', label: 'Dark', icon: Moon },
  { id: 'light', label: 'Light', icon: Sun },
  { id: 'system', label: 'System', icon: Monitor },
] as const;

export function SettingsPage() {
  const { theme, setTheme } = useSettings();
  const { configs, providerInfo, loading, error: llmError, createConfig, updateConfig, deleteConfig, refreshConfigs, testChat } = useLLM();
  const [activeTab, setActiveTab] = useState<TabId>('general');
  const [language, setLanguage] = useState('');
  const [timezone, setTimezone] = useState('');
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  useEffect(() => {
    settingsService.getSettings()
      .then(s => {
        setLanguage(s.user.language);
        setTimezone(s.user.timezone);
      })
      .catch(() => {});
  }, []);

  const saveGeneral = async () => {
    setSaveState('saving');
    try {
      await settingsService.updateUserSettings({ language, timezone, theme });
      setSaveState('saved');
    } catch {
      setSaveState('error');
    }
  };

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h1 className="text-2xl font-bold text-nexus-text">Settings</h1>
        <p className="text-nexus-text-secondary mt-1">Manage your preferences and configuration</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-4">
        <aside className="lg:col-span-1">
          <Card>
            <nav className="p-2 space-y-1" aria-label="Settings sections">
              {tabs.map(tab => {
                const Icon = tab.icon;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={cn(
                      'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-150',
                      'focus:outline-none focus:ring-2 focus:ring-nexus-accent',
                      activeTab === tab.id
                        ? 'bg-nexus-accent-dim text-nexus-accent'
                        : 'text-nexus-text-secondary hover:bg-nexus-bg-tertiary hover:text-nexus-text'
                    )}
                    aria-current={activeTab === tab.id ? 'page' : undefined}
                  >
                    <Icon className="w-5 h-5 flex-shrink-0" />
                    {tab.label}
                  </button>
                );
              })}
            </nav>
          </Card>
        </aside>

        <main className="lg:col-span-3 space-y-6">
          {activeTab === 'general' && (
            <Card>
              <CardHeader>
                <CardTitle>General</CardTitle>
                <CardDescription>Basic preferences for your Nexus experience</CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <div>
                  <span className="block text-sm font-medium text-nexus-text-secondary mb-3">Theme</span>
                  <div className="flex gap-2" role="radiogroup" aria-label="Theme">
                    {THEMES.map(t => {
                      const Icon = t.icon;
                      return (
                        <Button
                          key={t.id}
                          variant={theme === t.id ? 'primary' : 'secondary'}
                          size="sm"
                          className="gap-1.5"
                          role="radio"
                          aria-checked={theme === t.id}
                          onClick={() => setTheme(t.id)}
                        >
                          <Icon className="w-4 h-4" /> {t.label}
                        </Button>
                      );
                    })}
                  </div>
                </div>

                <Separator />

                <div className="grid gap-4 sm:grid-cols-2">
                  <Input label="Language" placeholder="en-US" value={language} onChange={(e) => { setLanguage(e.target.value); setSaveState('idle'); }} />
                  <Input label="Timezone" placeholder="UTC" value={timezone} onChange={(e) => { setTimezone(e.target.value); setSaveState('idle'); }} />
                </div>
                <div className="flex items-center gap-3">
                  <Button size="sm" onClick={saveGeneral} loading={saveState === 'saving'}>Save</Button>
                  {saveState === 'saved' && <span className="text-xs text-nexus-accent">Saved</span>}
                  {saveState === 'error' && <span className="text-xs text-nexus-danger">Could not save settings</span>}
                </div>
              </CardContent>
            </Card>
          )}

          {activeTab === 'ai' && (
            <>
              {llmError && <p className="text-sm text-nexus-danger" role="alert">{llmError.message}</p>}
              <LLMSettings
                configs={configs}
                providerInfo={providerInfo}
                loading={loading && configs.length === 0}
                testChat={testChat}
                onCreate={createConfig}
                onUpdate={updateConfig}
                onDelete={deleteConfig}
                onRefresh={refreshConfigs}
              />
            </>
          )}

        </main>
      </div>

      <div className="text-xs text-nexus-text-muted text-center">
        <Badge variant="default" size="sm">Nexus v0.2.0</Badge>
      </div>
    </div>
  );
}
