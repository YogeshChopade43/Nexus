import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, ChevronDown, ChevronRight, Plus, RefreshCw, Server, Trash2 } from 'lucide-react';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';
import { cn, getErrorMessage } from '../../lib/utils';
import { mcpService } from '../../services/mcp';
import type { McpServer, McpServerInput, McpTransport } from '../../types/mcp';

const STATUS_STYLES: Record<string, string> = {
  connected: 'bg-green-500/15 text-green-500',
  connecting: 'bg-blue-500/15 text-blue-500',
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

function formFrom(server: McpServer): FormState {
  return {
    name: server.name,
    transport: server.transport,
    command: server.command,
    args: joinArgs(server.args),
    env: toLines(server.env),
    url: server.url,
    headers: Object.entries(server.headers).map(([k, v]) => `${k}: ${v}`).join('\n'),
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

  // Poll while any server is still starting (npx/uvx can take a while on first launch).
  useEffect(() => {
    if (!servers.some(s => s.status === 'connecting')) return;
    const timer = setTimeout(() => void load(), 2000);
    return () => clearTimeout(timer);
  }, [servers, load]);

  const replace = (server: McpServer) => setServers(prev => prev.map(s => (s.id === server.id ? server : s)));

  const openForm = (server: McpServer | 'new') => {
    setEditing(server);
    setForm(server === 'new' ? EMPTY_FORM : formFrom(server));
    setFormError(null);
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
        <Button variant="primary" onClick={() => openForm('new')} className="gap-1.5">
          <Plus className="w-4 h-4" /> Add server
        </Button>
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
                      {server.error && server.status !== 'connected' && <p className="text-xs text-nexus-danger mt-1">{server.error}</p>}
                    </div>
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
                    <div className="px-4 pb-4">
                      {server.tools.length === 0 ? (
                        <p className="text-sm text-nexus-text-muted">No tools available{server.status !== 'connected' ? ' until the server connects' : ''}.</p>
                      ) : (
                        <ul className="grid gap-2 sm:grid-cols-2">
                          {server.tools.map(tool => (
                            <li key={tool.name} className="p-2 rounded border border-nexus-border">
                              <code className="text-xs text-nexus-accent">{tool.name}</code>
                              <p className="text-xs text-nexus-text-secondary mt-0.5 line-clamp-2">{tool.description.replace(`[${server.name}] `, '')}</p>
                            </li>
                          ))}
                        </ul>
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

          {editing !== 'new' && <p className="text-xs text-nexus-text-muted">Values shown as *** are kept unchanged.</p>}
          {formError && <p className="text-sm text-nexus-danger" role="alert">{formError}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setEditing(null)} disabled={busy === 'form'}>Cancel</Button>
            <Button type="submit" variant="primary" loading={busy === 'form'} disabled={busy === 'form'}>
              {busy === 'form' ? 'Connecting…' : 'Save & connect'}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
