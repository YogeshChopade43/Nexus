import { useState } from 'react';
import { cn } from '../lib/utils';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { Separator } from '../components/ui/Separator';
import { Badge } from '../components/ui/Badge';
import { User, Bell, Shield, Palette, Database, Globe, LogOut, Moon, Sun, Monitor, Cpu } from 'lucide-react';
import { Dropdown, DropdownItem } from '../components/ui/Dropdown';
import { useSettings } from '../hooks/useSettings';
import { useLLM } from '../hooks/useLLM';
import { LLMSettings } from '../components/llm/LLMSettings';

const tabs = [
  { id: 'general', label: 'General', icon: User },
  { id: 'notifications', label: 'Notifications', icon: Bell },
  { id: 'privacy', label: 'Privacy', icon: Shield },
  { id: 'editor', label: 'Editor', icon: Palette },
  { id: 'api', label: 'API', icon: Database },
  { id: 'accounts', label: 'Accounts', icon: Globe },
  { id: 'ai', label: 'AI', icon: Cpu },
];

export function SettingsPage() {
  const { theme, setTheme } = useSettings();
  const { configs, providerInfo, refreshConfigs, testChat } = useLLM();
  const [activeTab, setActiveTab] = useState<'general' | 'notifications' | 'privacy' | 'editor' | 'api' | 'accounts' | 'ai'>('general');

  const themeOptions: DropdownItem[] = [
    { label: 'Dark', icon: <Moon className='w-4 h-4' />, onClick: () => setTheme('dark') },
    { label: 'Light', icon: <Sun className='w-4 h-4' />, onClick: () => setTheme('light') },
    { label: 'System', icon: <Monitor className='w-4 h-4' />, onClick: () => setTheme('system') },
  ];

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
                    onClick={() => setActiveTab(tab.id as typeof activeTab)}
                    className={cn(
                      'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-150',
                      'focus:outline-none focus:ring-2 focus:ring-nexus-accent focus:ring-offset-2 focus:ring-offset-nexus-bg',
                      activeTab === tab.id
                        ? 'bg-nexus-accent-dim text-nexus-accent'
                        : 'text-nexus-text-secondary hover:bg-nexus-bg-tertiary hover:text-nexus-text'
                    )}
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
                  <label className="block text-sm font-medium text-nexus-text-secondary mb-3">Theme</label>
                  <Dropdown
                    trigger={
                      <Button variant={theme === 'dark' ? 'primary' : 'secondary'} className="w-full justify-between gap-2">
                        <span className="flex items-center gap-2">
                          {theme === 'dark' && <Moon className="w-4 h-4" />}
                          {theme === 'light' && <Sun className="w-4 h-4" />}
                          {theme === 'system' && <Monitor className="w-4 h-4" />}
                          <span>{theme.charAt(0).toUpperCase() + theme.slice(1)}</span>
                        </span>
                      </Button>
                    }
                    items={themeOptions}
                  />
                </div>

                <Separator />

                <div className="grid gap-4 sm:grid-cols-2">
                  <Input
                    label="Language"
                    placeholder="en-US"
                    defaultValue="en-US"
                    className="opacity-50"
                  />
                  <Input
                    label="Timezone"
                    placeholder="America/New_York"
                    defaultValue="America/New_York"
                    className="opacity-50"
                  />
                </div>
              </CardContent>
            </Card>
          )}

          {activeTab === 'notifications' && (
            <Card>
              <CardHeader>
                <CardTitle>Notifications</CardTitle>
                <CardDescription>Control how you receive notifications</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-col items-center justify-center py-8 text-nexus-text-muted">
                  <Bell className="w-12 h-12 text-nexus-text-muted/50 mb-3" />
                  <p>Notification settings will be available in a future release.</p>
                </div>
              </CardContent>
            </Card>
          )}

          {activeTab === 'privacy' && (
            <Card>
              <CardHeader>
                <CardTitle>Privacy</CardTitle>
                <CardDescription>Control your data and privacy settings</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-col items-center justify-center py-8 text-nexus-text-muted">
                  <Shield className="w-12 h-12 text-nexus-text-muted/50 mb-3" />
                  <p>Privacy settings will be available in a future release.</p>
                </div>
              </CardContent>
            </Card>
          )}

          {activeTab === 'editor' && (
            <Card>
              <CardHeader>
                <CardTitle>Editor</CardTitle>
                <CardDescription>Configure your code editor preferences</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-col items-center justify-center py-8 text-nexus-text-muted">
                  <Palette className="w-12 h-12 text-nexus-text-muted/50 mb-3" />
                  <p>Editor settings will be available in a future release.</p>
                </div>
              </CardContent>
            </Card>
          )}

          {activeTab === 'api' && (
            <Card>
              <CardHeader>
                <CardTitle>API Configuration</CardTitle>
                <CardDescription>Configure API connection settings</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-col items-center justify-center py-8 text-nexus-text-muted">
                  <Database className="w-12 h-12 text-nexus-text-muted/50 mb-3" />
                  <p>API settings will be available in a future release.</p>
                </div>
              </CardContent>
            </Card>
          )}

          {activeTab === 'ai' && (
            <LLMSettings
              configs={configs}
              providerInfo={providerInfo}
              loading={false}
              testChat={testChat}
              onCreate={async (data) => {
                const res = await fetch('/api/llm/', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify(data),
                });
                const config = await res.json();
                await refreshConfigs();
                return config;
              }}
              onUpdate={async (id) => {
                const res = await fetch(`/api/llm/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: '{}' });
                await refreshConfigs();
                return res.ok;
              }}
              onDelete={async (id) => {
                const res = await fetch(`/api/llm/${id}`, { method: 'DELETE' });
                await refreshConfigs();
                return res.ok;
              }}
              onRefresh={refreshConfigs}
            />
          )}

          {activeTab === 'accounts' && (
            <Card>
              <CardHeader>
                <CardTitle>Connected Accounts</CardTitle>
                <CardDescription>Manage your connected external accounts</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-col items-center justify-center py-8 text-nexus-text-muted">
                  <Globe className="w-12 h-12 text-nexus-text-muted/50 mb-3" />
                    <p>No connected accounts yet.</p>
                </div>
              </CardContent>
            </Card>
          )}
        </main>
      </div>

      <Card className="mt-6">
        <CardContent className="pt-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <LogOut className="w-5 h-5 text-nexus-danger" />
              <div>
                <p className="font-medium text-nexus-text">Sign out</p>
                <p className="text-sm text-nexus-text-secondary">Sign out of your Nexus account</p>
              </div>
            </div>
            <Button variant="ghost" size="sm" className="text-nexus-danger hover:text-nexus-danger-hover" disabled>
              Sign Out
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="text-xs text-nexus-text-muted text-center">
        <Badge variant="default" size="sm">Nexus v0.1.0</Badge>
      </div>
    </div>
  );
}
