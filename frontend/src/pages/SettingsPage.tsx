import { PageHeader } from '../components/ui/PageHeader';
import { useEffect, useState } from 'react';
import { cn } from '../lib/utils';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { TimezoneSelect } from '../components/ui/TimezoneSelect';
import { Separator } from '../components/ui/Separator';
import { Badge } from '../components/ui/Badge';
import { User, Moon, Sun, Monitor, Cpu, Download, UserCircle, ShieldCheck } from 'lucide-react';
import { AccountSettings } from '../components/settings/AccountSettings';
import { AdminSettings } from '../components/settings/AdminSettings';
import { useAuth } from '../hooks/useAuth';
import { useSearchParams } from 'react-router-dom';
import { useSettings } from '../hooks/useSettings';
import { useLLM } from '../hooks/useLLM';
import { LLMSettings } from '../components/llm/LLMSettings';
import { settingsService } from '../services/settings';
import { api } from '../services/api';

const tabs = [
  { id: 'general', label: 'General', icon: User },
  { id: 'ai', label: 'AI', icon: Cpu },
  { id: 'account', label: 'Account', icon: UserCircle },
  { id: 'admin', label: 'Admin', icon: ShieldCheck },
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
  const [searchParams] = useSearchParams();
  const { user } = useAuth();
  const visibleTabs = tabs.filter(t => t.id !== 'admin' || user?.isAdmin);
  const requested = visibleTabs.find(t => t.id === searchParams.get('tab'))?.id;
  const [activeTab, setActiveTab] = useState<TabId>(requested ?? 'general');
  const [timezone, setTimezone] = useState('');
  const [retentionDays, setRetentionDays] = useState('30');
  const [tokenLimit, setTokenLimit] = useState('0');
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  useEffect(() => {
    settingsService.getSettings()
      .then(s => {
        setTimezone(s.user.timezone);
        setRetentionDays(String(s.user.retentionDays ?? 30));
        setTokenLimit(String(s.user.dailyTokenLimit ?? 0));
      })
      .catch(() => {});
  }, []);

  const saveGeneral = async () => {
    setSaveState('saving');
    try {
      await settingsService.updateUserSettings({
        timezone, theme,
        retentionDays: Math.max(0, Number(retentionDays) || 0),
        dailyTokenLimit: Math.max(0, Number(tokenLimit) || 0),
      });
      setSaveState('saved');
    } catch {
      setSaveState('error');
    }
  };

  return (
    <div className="space-y-6 max-w-4xl">
      <PageHeader title="Settings" description="AI providers, your timezone and notifications, appearance and data." />

      <div className="grid gap-6 lg:grid-cols-4">
        <aside className="lg:col-span-1">
          <Card padding="none">
            <nav className="p-1.5 space-y-0.5" aria-label="Settings sections">
              {visibleTabs.map(tab => {
                const Icon = tab.icon;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={cn(
                      'flex h-8 w-full items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium transition-colors',
                      activeTab === tab.id
                        ? 'bg-nexus-bg-tertiary text-nexus-text'
                        : 'text-nexus-text-secondary hover:bg-nexus-bg-tertiary/60 hover:text-nexus-text'
                    )}
                    aria-current={activeTab === tab.id ? 'page' : undefined}
                  >
                    <Icon className={cn('h-4 w-4 flex-shrink-0', activeTab === tab.id ? 'text-nexus-accent-text' : 'text-nexus-text-muted')} />
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
                  <div className="w-full">
                    <label htmlFor="timezone" className="block text-sm font-medium text-nexus-text-secondary mb-1.5">Timezone</label>
                    <TimezoneSelect
                      id="timezone"
                      value={timezone}
                      onChange={(tz) => { setTimezone(tz); setSaveState('idle'); }}
                      className="w-full px-3 py-2 rounded-lg bg-nexus-bg-secondary border border-nexus-border hover:border-nexus-border-hover text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent"
                    />
                    <p className="mt-1.5 text-xs text-nexus-text-muted">Schedules without their own timezone run in this one.</p>
                  </div>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                <Input
                  label="Keep run history and activity for (days)"
                  type="number"
                  min={0}
                  value={retentionDays}
                  onChange={(e) => { setRetentionDays(e.target.value); setSaveState('idle'); }}
                  hint="Older runs and activity are deleted once a day. 0 keeps everything."
                />
                <Input
                  label="Daily AI token limit"
                  type="number"
                  min={0}
                  step={1000}
                  value={tokenLimit}
                  onChange={(e) => { setTokenLimit(e.target.value); setSaveState('idle'); }}
                  hint="Chat and workflows stop calling the AI once today's (UTC) usage reaches this. 0 = no limit."
                />
                </div>
                <div className="flex items-center gap-3">
                  <Button size="sm" onClick={saveGeneral} loading={saveState === 'saving'}>Save</Button>
                  {saveState === 'saved' && <span className="text-xs text-nexus-accent-text">Saved</span>}
                  {saveState === 'error' && <span className="text-xs text-nexus-danger">Could not save settings</span>}
                </div>
              </CardContent>
            </Card>
          )}

          {activeTab === 'general' && (
            <Card>
              <CardHeader>
                <CardTitle>Backup</CardTitle>
                <CardDescription>
                  One file with your workflows, servers, chats, settings and the key that unlocks their stored secrets.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <a
                  href={`${api.getBaseUrl()}/api/settings/backup`}
                  download
                  className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-nexus-accent text-nexus-on-accent text-sm font-medium hover:opacity-90"
                >
                  <Download className="w-4 h-4" /> Download backup
                </a>
                <p className="text-xs text-nexus-text-muted">
                  Works only on the computer running Nexus. Keep the file private: it contains every stored token and API key.
                  Restore steps are inside the zip.
                </p>
              </CardContent>
            </Card>
          )}

          {activeTab === 'account' && <AccountSettings />}
          {activeTab === 'admin' && user?.isAdmin && <AdminSettings />}

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
