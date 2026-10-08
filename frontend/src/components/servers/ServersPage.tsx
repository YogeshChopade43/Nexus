import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, BookOpen, ChevronDown, ChevronRight, LogIn, Plus, RefreshCw, Server, Trash2, Upload } from 'lucide-react';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';
import { cn, formatRelativeTime, getErrorMessage } from '../../lib/utils';
import { mcpService } from '../../services/mcp';
import type { ToolPolicy, McpLogs, McpServer, McpServerInput, McpTransport } from '../../types/mcp';
import { CATALOG, parseMcpConfig, type CatalogEntry } from './catalog';

const STATUS_STYLES: Record<string, string> = {
  connected: 'bg-green-500/15 text-green-500',
  connecting: 'bg-blue-500/15 text-blue-500',
  needs_auth: 'bg-amber-500/15 text-amber-500',
  error: 'bg-red-500/15 text-red-500',
  stopped: 'bg-gray-500/15 text-nexus-text-muted',
};

const inputClass =
  'w-full px-3 py-2 rounded-lg bg-nexus-bg-tertiary border border-nexus-border text-sm text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent';

/** "KEY=value" lines <-> object. Masked values ("***") round-trip so stored secrets are kept. */
function toLines(map: Record<string, string>): string {
  return Object.entries(map).map(([k, v]) => `${k}=${v}`).join('\n');
}

function fromLines(text: string, separator: '=' | ':'): Record<string, string> {
  const result: Record<string, string> = {};
  for (const line of text.split('\n')) {
    const index = line.indexOf(separator);
    if (index > 0) result[line.slice(0, index).trim()] = line.slice(index + 1).trim();
  }
  return result;
}

/** Split a command line into args, honouring double quotes (paths with spaces on Windows). */
function splitArgs(text: string): string[] {
  return (text.match(/"[^"]*"|\S+/g) ?? []).map(a => a.replace(/^"|"$/g, ''));
}

function joinArgs(args: string[]): string {
  return args.map(a => (/\s/.test(a) ? `"${a}"` : a)).join(' ');
}

interface FormState {
  name: string;
  transport: McpTransport;
  command: string;
  args: string;
  env: string;
  url: string;
  headers: string;
}

const EMPTY_FORM: FormState = { name: '', transport: 'stdio', command: '', args: '', env: '', url: '', headers: '' };

function formFrom(server: McpServerInput): FormState {
  return {
    name: server.name,
    transport: server.transport,
    command: server.command ?? '',
    args: joinArgs(server.args ?? []),
    env: toLines(server.env ?? {}),
    url: server.url ?? '',
    headers: Object.entries(server.headers ?? {}).map(([k, v]) => `${k}: ${v}`).join('\n'),
  };
}

export function ServersPage() {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<McpServer | 'new' | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | 'form' | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [formNote, setFormNote] = useState<string | null>(null);
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState('');
  const [importResult, setImportResult] = useState<string | null>(null);
  const [logs, setLogs] = useState<{ id: number; data: McpLogs } | null>(null);

  const load = useCallback(async () => {
    try {
      setServers(await mcpService.list());
      setError(null);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll while a server is starting (npx/uvx can take a while on first launch) or waiting for sign-in.
  useEffect(() => {
    if (!servers.some(s => s.status === 'connecting' || s.status === 'needs_auth')) return;
    const timer = setTimeout(() => void load(), 2000);
    return () => clearTimeout(timer);
  }, [servers, load]);

  const replace = (server: McpServer) => setServers(prev => prev.map(s => (s.id === server.id ? server : s)));

  const openForm = (server: McpServer | 'new', fromCatalog?: CatalogEntry) => {
    setEditing(server);
    setForm(fromCatalog ? formFrom(fromCatalog.server) : server === 'new' ? EMPTY_FORM : formFrom(server));
    setFormNote(fromCatalog?.note ?? null);
    setFormError(null);
    setCatalogOpen(false);
  };

  const importConfig = async () => {
    setImportResult(null);
    let parsed: ReturnType<typeof parseMcpConfig>;
    try {
      parsed = parseMcpConfig(importText);
    } catch (err) {
      setImportResult(`Could not read that file: ${getErrorMessage(err)}`);
      return;
    }
    setBusy('form');
    const results = await Promise.allSettled(parsed.servers.map(server => mcpService.create(server)));
    setBusy(null);
    const failed = results.flatMap((r, i) => (r.status === 'rejected' ? [`${parsed.servers[i].name}: ${getErrorMessage(r.reason)}`] : []));
    const added = results.length - failed.length;
    setImportResult([`Added ${added} server(s).`, ...failed.map(f => `Failed ${f}`), ...parsed.skipped.map(s => `Skipped ${s}`)].join('\n'));
    if (added) await load();
  };

  const toggleLogs = async (server: McpServer) => {
    if (logs?.id === server.id) { setLogs(null); return; }
    try {
      setLogs({ id: server.id, data: await mcpService.logs(server.id) });
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const submit = async () => {
    const input: McpServerInput = {
      name: form.name.trim(),
      transport: form.transport,
      ...(form.transport === 'stdio'
        ? { command: form.command.trim(), args: splitArgs(form.args), env: fromLines(form.env, '=') }
        : { url: form.url.trim(), headers: fromLines(form.headers, ':') }),
    };
    setBusy('form');
    setFormError(null);
    try {
      const saved = editing === 'new' || editing === null
        ? await mcpService.create(input)
        : await mcpService.update(editing.id, input);
      setEditing(null);
      setExpanded(saved.id);
      await load();
    } catch (err) {
      setFormError(getErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const act = async (server: McpServer, action: () => Promise<McpServer | void>) => {
    setBusy(server.id);
    try {
      const result = await action();
      if (result) replace(result);
      else await load();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-nexus-text">MCP Servers</h1>
          <p className="text-nexus-text-secondary mt-1">
            Connect any app through its MCP server. Its tools become available to the agent and to workflows.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 justify-end">
          <Button variant="secondary" onClick={() => setCatalogOpen(true)} className="gap-1.5">
            <BookOpen className="w-4 h-4" /> Catalog
          </Button>
          <Button variant="secondary" onClick={() => { setImportOpen(true); setImportResult(null); }} className="gap-1.5">
            <Upload className="w-4 h-4" /> Import
          </Button>
          <Button variant="primary" onClick={() => openForm('new')} className="gap-1.5">
            <Plus className="w-4 h-4" /> Add server
          </Button>
        </div>
      </div>

      {error && (
        <Card className="p-4 border-nexus-danger/30">
          <div className="flex items-center gap-2 text-nexus-danger"><AlertCircle className="w-5 h-5" />{error}</div>
        </Card>
      )}

      {loading ? (
        <p className="text-sm text-nexus-text-muted">Loading…</p>
      ) : servers.length === 0 ? (
        <Card className="p-10 text-center">
          <Server className="w-12 h-12 mx-auto text-nexus-text-muted/50 mb-3" />
          <h3 className="text-lg font-medium text-nexus-text">No MCP servers yet</h3>
          <p className="text-sm text-nexus-text-muted mt-1 max-w-md mx-auto">
            Add a local server launched by a command (for example <code>npx -y @notionhq/notion-mcp-server</code>)
            or a remote server URL with an auth header.
          </p>
        </Card>
      ) : (
        <ul className="space-y-3">
          {servers.map(server => {
            const open = expanded === server.id;
            return (
              <li key={server.id}>
                <Card>
                  <div className="p-4 flex flex-wrap items-center gap-3">
                    <button onClick={() => setExpanded(open ? null : server.id)} aria-label={open ? 'Hide tools' : 'Show tools'} className="text-nexus-text-muted">
                      {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                    </button>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-nexus-text">{server.name}</span>
                        <code className="text-xs text-nexus-text-muted">{server.slug}__*</code>
                        <span className={cn('px-2 py-0.5 rounded text-xs font-medium', STATUS_STYLES[server.status])}>{server.status}</span>
                        {server.status === 'connected' && <span className="text-xs text-nexus-text-muted">{server.tools.length} tool(s)</span>}
                      </div>
                      <p className="text-xs text-nexus-text-muted truncate mt-0.5 font-mono">
                        {server.transport === 'stdio' ? `${server.command} ${joinArgs(server.args)}` : server.url}
                      </p>
                      {server.error && server.status !== 'connected' && server.status !== 'needs_auth' && <p className="text-xs text-nexus-danger mt-1">{server.error}</p>}
                      {server.status === 'needs_auth' && <p className="text-xs text-amber-500 mt-1">This server needs you to sign in before Nexus can use it.</p>}
                    </div>
                    {server.status === 'needs_auth' && server.auth_url && (
                      <a href={server.auth_url} target="_blank" rel="noreferrer"
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-nexus-accent text-nexus-bg text-sm font-medium hover:opacity-90">
                        <LogIn className="w-4 h-4" /> Sign in
                      </a>
                    )}
                    {server.signed_in && server.status !== 'needs_auth' && (
                      <Button variant="ghost" size="sm" disabled={busy === server.id}
                        onClick={() => { if (window.confirm(`Sign out of ${server.name}? You'll need to sign in again to use it.`)) void act(server, () => mcpService.signOut(server.id)); }}>
                        Sign out
                      </Button>
                    )}
                    <label className="flex items-center gap-2 text-sm text-nexus-text-secondary">
                      <input
                        type="checkbox"
                        checked={server.enabled}
                        disabled={busy === server.id}
                        onChange={(e) => void act(server, () => mcpService.update(server.id, { enabled: e.target.checked }))}
                      />
                      Enabled
                    </label>
                    <Button variant="ghost" size="sm" aria-label="Reconnect" disabled={busy === server.id || !server.enabled}
                      onClick={() => void act(server, () => mcpService.restart(server.id))}>
                      <RefreshCw className={cn('w-4 h-4', busy === server.id && 'animate-spin')} />
                    </Button>
                    <Button variant="secondary" size="sm" onClick={() => openForm(server)}>Edit</Button>
                    <Button variant="ghost" size="sm" aria-label="Remove server" className="text-nexus-danger"
                      onClick={() => {
                        if (window.confirm(`Remove ${server.name}? Workflows using its tools will fail.`)) {
                          void act(server, () => mcpService.remove(server.id));
                        }
                      }}>
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                  {open && (
                    <div className="px-4 pb-4 space-y-3">
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-nexus-text-muted">
                        {server.health?.connected_since && <span>Connected {formatRelativeTime(server.health.connected_since)}</span>}
                        {server.health && <span>{server.health.calls} call(s), {server.health.failures} failed</span>}
                        {server.health?.last_call_at && <span>Last used {formatRelativeTime(server.health.last_call_at)}</span>}
                        <button type="button" className="underline" onClick={() => void toggleLogs(server)}>
                          {logs?.id === server.id ? 'Hide logs' : 'Show logs'}
                        </button>
                      </div>
                      {logs?.id === server.id && (
                        <div className="space-y-2">
                          <ul className="text-xs text-nexus-text-secondary space-y-0.5 max-h-40 overflow-y-auto">
                            {logs.data.events.length === 0 && <li className="text-nexus-text-muted">No connection events yet.</li>}
                            {[...logs.data.events].reverse().map((event, i) => (
                              <li key={i}><span className="text-nexus-text-muted font-mono">{event.at.replace('T', ' ').replace('Z', '')}</span> {event.message}</li>
                            ))}
                          </ul>
                          {server.transport === 'stdio' && (
                            <pre className="text-xs text-nexus-text-secondary bg-nexus-bg-tertiary/50 rounded p-2 max-h-64 overflow-auto whitespace-pre-wrap" aria-label="Server error output">
                              {logs.data.stderr.trim() || 'The server has not written any error output.'}
                            </pre>
                          )}
                        </div>
                      )}
                      {server.tools.length + server.blocked_tools.length === 0 ? (
                        <p className="text-sm text-nexus-text-muted">No tools available{server.status !== 'connected' ? ' until the server connects' : ''}.</p>
                      ) : (
                        <>
                          <p className="text-xs text-nexus-text-muted mb-2">
                            Allow: runs without asking. Ask: the chat agent asks you first. Block: hidden from the agent and workflows.
                          </p>
                          <ul className="grid gap-2 sm:grid-cols-2">
                            {[...server.tools, ...server.blocked_tools].map(tool => (
                              <li key={tool.name} className={cn('p-2 rounded border border-nexus-border', tool.policy === 'block' && 'opacity-60')}>
                                <div className="flex items-center justify-between gap-2">
                                  <code className="text-xs text-nexus-accent truncate">{tool.name}</code>
                                  <select
                                    value={tool.policy}
                                    disabled={busy === server.id}
                                    aria-label={`Policy for ${tool.name}`}
                                    onChange={(e) => void act(server, () => mcpService.update(server.id, {
                                      tool_policies: { ...server.tool_policies, [tool.remote_name]: e.target.value as ToolPolicy },
                                    }))}
                                    className="px-1.5 py-0.5 rounded bg-nexus-bg-tertiary border border-nexus-border text-xs text-nexus-text"
                                  >
                                    <option value="allow">Allow</option>
                                    <option value="ask">Ask</option>
                                    <option value="block">Block</option>
                                  </select>
                                </div>
                                <p className="text-xs text-nexus-text-secondary mt-0.5 line-clamp-2">{tool.description.replace(`[${server.name}] `, '')}</p>
                              </li>
                            ))}
                          </ul>
                        </>
                      )}
                    </div>
                  )}
                </Card>
              </li>
            );
          })}
        </ul>
      )}

      <Modal open={editing !== null} onClose={() => busy !== 'form' && setEditing(null)} title={editing === 'new' ? 'Add MCP server' : 'Edit MCP server'} size="lg">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="block text-xs font-medium text-nexus-text-secondary mb-1">Name</span>
              <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Notion" className={inputClass} />
            </label>
            <label className="block">
              <span className="block text-xs font-medium text-nexus-text-secondary mb-1">Type</span>
              <select value={form.transport} onChange={(e) => setForm({ ...form, transport: e.target.value as McpTransport })} className={inputClass}>
                <option value="stdio">Local command (stdio)</option>
                <option value="http">Remote URL (streamable HTTP)</option>
              </select>
            </label>
          </div>

          {form.transport === 'stdio' ? (
            <>
              <div className="grid gap-4 sm:grid-cols-3">
                <label className="block">
                  <span className="block text-xs font-medium text-nexus-text-secondary mb-1">Command</span>
                  <input value={form.command} onChange={(e) => setForm({ ...form, command: e.target.value })} placeholder="npx" className={cn(inputClass, 'font-mono')} />
                </label>
                <label className="block sm:col-span-2">
                  <span className="block text-xs font-medium text-nexus-text-secondary mb-1">Arguments</span>
                  <input value={form.args} onChange={(e) => setForm({ ...form, args: e.target.value })} placeholder="-y @notionhq/notion-mcp-server" className={cn(inputClass, 'font-mono')} />
                </label>
              </div>
              <label className="block">
                <span className="block text-xs font-medium text-nexus-text-secondary mb-1">Environment variables (one KEY=value per line, stored encrypted)</span>
                <textarea rows={3} value={form.env} onChange={(e) => setForm({ ...form, env: e.target.value })} placeholder="NOTION_TOKEN=ntn_..." className={cn(inputClass, 'font-mono')} />
              </label>
              <p className="text-xs text-nexus-text-muted">The command runs on the machine running the Nexus backend. Only add servers you trust.</p>
            </>
          ) : (
            <>
              <label className="block">
                <span className="block text-xs font-medium text-nexus-text-secondary mb-1">Server URL</span>
                <input value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="https://api.githubcopilot.com/mcp/" className={cn(inputClass, 'font-mono')} />
              </label>
              <label className="block">
                <span className="block text-xs font-medium text-nexus-text-secondary mb-1">Headers (one "Name: value" per line, stored encrypted)</span>
                <textarea rows={2} value={form.headers} onChange={(e) => setForm({ ...form, headers: e.target.value })} placeholder="Authorization: Bearer ghp_..." className={cn(inputClass, 'font-mono')} />
              </label>
            </>
          )}

          {formNote && <p className="text-sm text-amber-500">{formNote}</p>}
          {form.transport === 'http' && (
            <p className="text-xs text-nexus-text-muted">Servers that use sign-in (OAuth) ask you to sign in after saving; leave the headers empty for those.</p>
          )}
          {editing !== 'new' && editing !== null && <p className="text-xs text-nexus-text-muted">Values shown as *** are kept unchanged.</p>}
          {formError && <p className="text-sm text-nexus-danger" role="alert">{formError}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setEditing(null)} disabled={busy === 'form'}>Cancel</Button>
            <Button type="submit" variant="primary" loading={busy === 'form'} disabled={busy === 'form'}>
              {busy === 'form' ? 'Connecting…' : 'Save & connect'}
            </Button>
          </div>
        </form>
      </Modal>

      <Modal open={catalogOpen} onClose={() => setCatalogOpen(false)} title="Server catalog" size="lg">
        <p className="text-sm text-nexus-text-secondary mb-3">Popular servers. Picking one fills in the form; you can change anything before saving.</p>
        <ul className="grid gap-2 sm:grid-cols-2">
          {CATALOG.map(entry => (
            <li key={entry.server.name}>
              <button type="button" onClick={() => openForm('new', entry)}
                className="w-full text-left p-3 rounded-lg border border-nexus-border hover:border-nexus-accent transition-colors">
                <span className="font-medium text-nexus-text">{entry.server.name}</span>
                <span className="ml-2 text-xs text-nexus-text-muted">{entry.server.transport === 'http' ? 'hosted' : 'local'}</span>
                <p className="text-xs text-nexus-text-secondary mt-1">{entry.description}</p>
              </button>
            </li>
          ))}
        </ul>
      </Modal>

      <Modal open={importOpen} onClose={() => busy !== 'form' && setImportOpen(false)} title="Import MCP servers" size="lg">
        <div className="space-y-3">
          <p className="text-sm text-nexus-text-secondary">
            Paste or choose a config file from Claude Desktop (<code>claude_desktop_config.json</code>), Claude Code
            (<code>.mcp.json</code> or <code>~/.claude.json</code>), Cursor or VS Code (<code>.vscode/mcp.json</code>).
          </p>
          <input type="file" accept=".json,application/json" aria-label="Choose a config file"
            onChange={(e) => { const file = e.target.files?.[0]; if (file) void file.text().then(setImportText); }}
            className="text-sm text-nexus-text-secondary" />
          <textarea rows={8} value={importText} onChange={(e) => setImportText(e.target.value)} aria-label="Config file contents"
            placeholder='{"mcpServers": {"notion": {"command": "npx", "args": ["-y", "@notionhq/notion-mcp-server"]}}}'
            className={cn(inputClass, 'font-mono text-xs')} />
          {importResult && <pre className="text-sm text-nexus-text-secondary whitespace-pre-wrap" role="status">{importResult}</pre>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setImportOpen(false)} disabled={busy === 'form'}>Close</Button>
            <Button variant="primary" onClick={() => void importConfig()} loading={busy === 'form'} disabled={busy === 'form' || !importText.trim()}>
              {busy === 'form' ? 'Connecting…' : 'Import'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
