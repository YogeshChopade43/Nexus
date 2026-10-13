import { useEffect, useState, type FormEvent } from 'react';
import { CalendarDays, CheckCircle2, Copy, Globe, Hash, LogIn, Mail, MessagesSquare, Plug, Rss, Send, Trash2, XCircle, type LucideIcon } from 'lucide-react';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { Modal } from '../ui/Modal';
import { fieldClass } from '../ui/Input';
import { cn, getErrorMessage } from '../../lib/utils';
import { integrationService, type Integration, type IntegrationField, type IntegrationKind } from '../../services/integrations';

const ICONS: Record<string, LucideIcon> = { Mail, CalendarDays, Rss, Send, Globe, Hash, MessagesSquare };
const CHAT_APPS = ['telegram', 'slack', 'discord'];

export function KindIcon({ icon, className }: { icon: string; className?: string }) {
  if (icon === 'Google') {  // no brand logos in Lucide: Google's "G" in its colours
    return (
      <span aria-hidden className={cn('flex shrink-0 items-center justify-center rounded-lg border border-nexus-border bg-white text-lg font-bold', className)}>
        <span className="bg-[conic-gradient(from_-45deg,#ea4335_0_25%,#4285f4_0_50%,#34a853_0_75%,#fbbc05_0)] bg-clip-text text-transparent">G</span>
      </span>
    );
  }
  const Icon = ICONS[icon] ?? Plug;
  return (
    <span aria-hidden className={cn('flex shrink-0 items-center justify-center rounded-lg border border-nexus-border bg-nexus-bg-tertiary text-nexus-text-secondary', className)}>
      <Icon className="h-[45%] w-[45%]" />
    </span>
  );
}

/** Apps Nexus connects to itself (no MCP server needed), as cards at the top of the Marketplace. */
export function BuiltInSection({ kinds, integrations, onOpen }: {
  kinds: IntegrationKind[];
  integrations: Integration[];
  onOpen: (kind: IntegrationKind) => void;
}) {
  if (kinds.length === 0) return null;
  return (
    <section aria-label="Built-in" className="space-y-2">
      <h2 className="text-xs font-medium uppercase tracking-wider text-nexus-text-muted">Built-in · no setup on the app&apos;s side</h2>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {kinds.map(kind => {
          const count = integrations.filter(i => i.kind === kind.id).length;
          return (
            <button key={kind.id} type="button" onClick={() => onOpen(kind)}
              className="group flex min-w-0 gap-3 rounded-xl border border-nexus-border bg-nexus-bg-secondary p-4 text-left shadow-surface transition-[border-color,background-color,transform] duration-150 hover:-translate-y-px hover:border-nexus-border-hover hover:bg-nexus-bg-tertiary/40">
              <KindIcon icon={kind.icon} className="h-10 w-10" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-semibold text-nexus-text">{kind.title}</span>
                <span className="mt-1 line-clamp-2 block text-[13px] leading-snug text-nexus-text-secondary">{kind.description}</span>
                <span className="mt-2.5 flex gap-1.5">
                  {count > 0 ? <Badge size="sm" variant="success">{count} connected</Badge> : <Badge size="sm">Built-in</Badge>}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function FieldInput({ field, value, onChange }: { field: IntegrationField; value: string; onChange: (value: string) => void }) {
  const id = `integration-${field.name}`;
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-[13px] font-medium text-nexus-text">
        {field.label}{!field.required && <span className="font-normal text-nexus-text-muted"> (optional)</span>}
      </label>
      <input id={id} type={field.type} value={value} required={field.required} autoComplete={field.type === 'password' ? 'new-password' : 'off'}
        placeholder={field.default !== null && field.default !== undefined ? String(field.default) : undefined}
        onChange={(e) => onChange(e.target.value)} className={fieldClass} />
      {field.help && <p className="text-xs text-nexus-text-muted">{field.help}</p>}
    </div>
  );
}

/** Connect an integration of one kind, and manage the ones already connected. */
export function IntegrationModal({ kind, integrations, onClose, onChanged }: {
  kind: IntegrationKind;
  integrations: Integration[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const mine = integrations.filter(i => i.kind === kind.id);
  const [name, setName] = useState(kind.title.split(' ')[0]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [checks, setChecks] = useState<Record<number, { ok: boolean; message: string } | 'running'>>({});
  const [copied, setCopied] = useState(false);
  const isGoogle = kind.id === 'google';
  const waiting = mine.some(i => i.status === 'needs_auth');

  useEffect(() => {  // a sign-in finishes in another tab: refresh until it shows up here
    if (!waiting) return;
    const timer = setInterval(onChanged, 3000);
    return () => clearInterval(timer);
  }, [waiting, onChanged]);

  const openSignIn = (url: string) => {
    window.open(url, '_blank', 'noopener');
    setDone('Google opened in a new tab: finish signing in there, then come back. This list updates by itself.');
  };

  const signIn = async (integration: Integration) => {
    try {
      openSignIn((await integrationService.signIn(integration.id)).auth_url);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const connect = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const config = Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim()).map(([k, v]) => {
        const field = kind.fields.find(f => f.name === k);
        return [k, field?.type === 'number' ? Number(v) : v.trim()];
      }));
      if (isGoogle) {
        const started = await integrationService.googleStart(name.trim() || 'Google', config);
        openSignIn(started.auth_url);
        setValues({});
        onChanged();
        return;
      }
      const created = await integrationService.create(kind.id, name.trim() || kind.title, config);
      setDone(`Connected "${created.name}". ${created.message}`);
      setValues({});
      onChanged();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const test = async (integration: Integration) => {
    setChecks(prev => ({ ...prev, [integration.id]: 'running' }));
    try {
      const result = await integrationService.test(integration.id);
      setChecks(prev => ({ ...prev, [integration.id]: result }));
    } catch (err) {
      setChecks(prev => ({ ...prev, [integration.id]: { ok: false, message: getErrorMessage(err) } }));
    }
  };

  const remove = async (integration: Integration) => {
    if (!window.confirm(`Remove ${integration.name}? Workflows using it will fail.`)) return;
    try {
      await integrationService.remove(integration.id);
      onChanged();
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const basic = kind.fields.filter(f => !f.advanced);
  const advanced = kind.fields.filter(f => f.advanced);
  const set = (field: string) => (value: string) => setValues(prev => ({ ...prev, [field]: value }));

  return (
    <Modal open onClose={onClose} title={kind.title} description={kind.description} size="lg">
      <div className="space-y-5">
        {mine.length > 0 && (
          <section aria-label="Connected" className="space-y-2">
            <h3 className="text-xs font-medium uppercase tracking-wider text-nexus-text-muted">Connected</h3>
            <ul className="divide-y divide-nexus-border rounded-lg border border-nexus-border">
              {mine.map(integration => {
                const check = checks[integration.id];
                return (
                  <li key={integration.id} className="space-y-1.5 p-3">
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-medium text-nexus-text">{integration.name}</span>
                        <span className="block truncate text-xs text-nexus-text-muted">
                          {String(integration.settings.address ?? integration.settings.account ?? integration.settings.url ?? '')}
                          {integration.settings.address || integration.settings.account || integration.settings.url ? ' · ' : ''}
                          {integration.status !== 'needs_auth' ? `${integration.tools.length} tools`
                            : CHAT_APPS.includes(integration.kind) ? 'waiting for you to send the bot its code' : 'waiting for sign-in'}
                        </span>
                      </span>
                      {integration.status === 'needs_auth' && integration.kind === 'google' && (
                        <Button size="sm" aria-label={`Sign in to ${integration.name}`} onClick={() => void signIn(integration)}>
                          <LogIn className="h-3.5 w-3.5" /> Sign in
                        </Button>
                      )}
                      <Button variant="secondary" size="sm" disabled={check === 'running'} aria-label={`Test ${integration.name}`}
                        onClick={() => void test(integration)}>
                        {check === 'running' ? 'Testing…' : 'Test'}
                      </Button>
                      <Button variant="ghost" size="sm" className="w-8 px-0 text-nexus-text-muted hover:text-nexus-danger"
                        aria-label={`Remove ${integration.name}`} onClick={() => void remove(integration)}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                    {integration.status === 'needs_auth' && integration.kind === 'telegram' && (
                      <div className="flex flex-wrap items-center gap-2 rounded-md bg-nexus-accent/5 p-2 text-xs text-nexus-text-secondary">
                        <a href={`https://t.me/${String(integration.settings.bot_username)}?start=${String(integration.settings.pairing_code)}`}
                          target="_blank" rel="noreferrer"
                          className="inline-flex h-7 items-center gap-1.5 rounded-md bg-nexus-accent px-2.5 font-medium text-nexus-on-accent hover:no-underline">
                          <Send className="h-3.5 w-3.5" aria-hidden /> Open @{String(integration.settings.bot_username)} in Telegram
                        </a>
                        <span>and tap <b>Start</b>, or send it <code className="font-mono text-nexus-text">/start {String(integration.settings.pairing_code)}</code></span>
                      </div>
                    )}
                    {integration.status === 'needs_auth' && integration.kind === 'slack' && (
                      <p className="rounded-md bg-nexus-accent/5 p-2 text-xs text-nexus-text-secondary">
                        In Slack, open <b>@{String(integration.settings.bot_username)}</b> (Apps in the sidebar) and send it{' '}
                        <code className="font-mono text-nexus-text">{String(integration.settings.pairing_code)}</code>
                      </p>
                    )}
                    {integration.status === 'needs_auth' && integration.kind === 'discord' && (
                      <div className="flex flex-wrap items-center gap-2 rounded-md bg-nexus-accent/5 p-2 text-xs text-nexus-text-secondary">
                        <a href={String(integration.settings.invite_url)} target="_blank" rel="noreferrer"
                          className="inline-flex h-7 items-center gap-1.5 rounded-md bg-nexus-accent px-2.5 font-medium text-nexus-on-accent hover:no-underline">
                          <MessagesSquare className="h-3.5 w-3.5" aria-hidden /> Add @{String(integration.settings.bot_username)} to a server
                        </a>
                        <span>you&apos;re in, then DM the bot <code className="font-mono text-nexus-text">link {String(integration.settings.pairing_code)}</code></span>
                      </div>
                    )}
                    {check && check !== 'running' && (
                      <p role="status" className={cn('flex items-center gap-1 text-xs', check.ok ? 'text-nexus-success' : 'text-nexus-danger')}>
                        {check.ok ? <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> : <XCircle className="h-3.5 w-3.5" aria-hidden />}
                        {check.message}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        <form onSubmit={(e) => void connect(e)} className="space-y-3">
          <h3 className="text-xs font-medium uppercase tracking-wider text-nexus-text-muted">{mine.length ? 'Connect another' : 'Connect'}</h3>
          <div className="space-y-1">
            <label htmlFor="integration-name" className="block text-[13px] font-medium text-nexus-text">Name</label>
            <input id="integration-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={60} className={fieldClass} />
            <p className="text-xs text-nexus-text-muted">How the agent and your workflows will refer to it, e.g. &ldquo;Work email&rdquo;. Mention it in chat with @.</p>
          </div>
          {isGoogle && kind.redirect_uri && (
            <div className="space-y-2 rounded-lg border border-nexus-border bg-nexus-bg-tertiary/40 p-3 text-xs text-nexus-text-secondary">
              <p className="font-medium text-nexus-text">One-time setup in Google Cloud (about 10 minutes)</p>
              <ol className="list-decimal space-y-1 pl-4">
                <li>Open <a href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noreferrer">console.cloud.google.com</a> and create a project.</li>
                <li>Enable the <b>Gmail API</b>, <b>Google Calendar API</b> and <b>Google Drive API</b> (APIs &amp; Services › Library).</li>
                <li>OAuth consent screen: choose <b>External</b>, add your Google address as a test user. While it's in Testing, Google ends the sign-in every 7 days; publishing it stops that, and Google then shows an &ldquo;unverified app&rdquo; warning you can click through for your own account.</li>
                <li>Credentials › Create credentials › <b>OAuth client ID</b> › Web application, with this authorized redirect URI:</li>
              </ol>
              <div className="flex items-center gap-2">
                <code className="min-w-0 flex-1 truncate rounded border border-nexus-border bg-nexus-bg-secondary px-2 py-1.5 font-mono text-[11px] text-nexus-text">{kind.redirect_uri}</code>
                <Button type="button" variant="secondary" size="sm" className="h-7 px-2" aria-label="Copy redirect URI"
                  onClick={() => { void navigator.clipboard?.writeText(kind.redirect_uri ?? '').then(() => setCopied(true)); }}>
                  <Copy className="h-3.5 w-3.5" />{copied ? 'Copied' : ''}
                </Button>
              </div>
              <p>Then paste the client ID and secret below.</p>
            </div>
          )}
          {kind.manifest && (
            <div className="space-y-2 rounded-lg border border-nexus-border bg-nexus-bg-tertiary/40 p-3 text-xs text-nexus-text-secondary">
              <p className="font-medium text-nexus-text">One-time setup in Slack (about 3 minutes)</p>
              <ol className="list-decimal space-y-1 pl-4">
                <li>Open <a href="https://api.slack.com/apps?new_app=1" target="_blank" rel="noreferrer">api.slack.com/apps</a> › Create New App › <b>From a manifest</b>, pick your workspace and paste this:</li>
              </ol>
              <div className="relative">
                <pre className="max-h-32 overflow-auto rounded border border-nexus-border bg-nexus-bg-secondary p-2 font-mono text-[11px] text-nexus-text">{kind.manifest}</pre>
                <Button type="button" variant="secondary" size="sm" className="absolute right-1.5 top-1.5 h-7 px-2" aria-label="Copy manifest"
                  onClick={() => { void navigator.clipboard?.writeText(kind.manifest ?? '').then(() => setCopied(true)); }}>
                  <Copy className="h-3.5 w-3.5" />{copied ? 'Copied' : ''}
                </Button>
              </div>
              <p>Then <b>Install to Workspace</b> and paste the two tokens below.</p>
            </div>
          )}
          {basic.map(field => <FieldInput key={field.name} field={field} value={values[field.name] ?? ''} onChange={set(field.name)} />)}
          {advanced.length > 0 && (
            <details className="rounded-lg border border-nexus-border px-3 py-2">
              <summary className="text-[13px] text-nexus-text-secondary">More settings</summary>
              <div className="mt-3 space-y-3">
                {advanced.map(field => <FieldInput key={field.name} field={field} value={values[field.name] ?? ''} onChange={set(field.name)} />)}
              </div>
            </details>
          )}
          {error && <p role="alert" className="text-[13px] text-nexus-danger">{error}</p>}
          {done && <p role="status" className="flex items-center gap-1.5 text-[13px] text-nexus-success"><CheckCircle2 className="h-4 w-4" aria-hidden />{done}</p>}
          <div className="flex justify-end">
            <Button type="submit" size="sm" loading={busy}>{isGoogle ? 'Sign in with Google' : 'Connect'}</Button>
          </div>
          <p className="text-xs text-nexus-text-muted">
            {isGoogle ? 'Your client secret and Google sign-in are stored encrypted on this computer; Nexus talks to Google directly.'
              : 'Nexus checks the connection before saving. Settings are stored encrypted on this computer.'}
          </p>
        </form>
      </div>
    </Modal>
  );
}
