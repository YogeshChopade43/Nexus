import { useEffect, useState } from 'react';
import { LogIn, RefreshCw, Trash2 } from 'lucide-react';
import { Button } from '../ui/Button';
import { cn, formatRelativeTime, getErrorMessage } from '../../lib/utils';
import { mcpService } from '../../services/mcp';
import type { McpLogs, McpServer, ToolPolicy } from '../../types/mcp';
import { ServerFormModal } from './ServerFormModal';

const STATUS_STYLES: Record<string, string> = {
  connected: 'bg-green-500/15 text-green-500',
  connecting: 'bg-blue-500/15 text-blue-500',
  needs_auth: 'bg-amber-500/15 text-amber-500',
  error: 'bg-red-500/15 text-red-500',
  stopped: 'bg-gray-500/15 text-nexus-text-muted',
};

/** Status, tools and their policies, logs, sign-in, edit and remove for one installed server.
 *  ``onChanged(null)`` means it was removed. */
export function InstalledServer({ server: initial, onChanged }: {
  server: McpServer;
  onChanged: (server: McpServer | null) => void;
}) {
  const [server, setServer] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<McpLogs | null>(null);
  const [editing, setEditing] = useState(false);
  const [check, setCheck] = useState<{ ok: boolean; message: string } | 'running' | null>(null);

  useEffect(() => setServer(initial), [initial]);

  // Follow a server that is connecting or waiting for sign-in.
  useEffect(() => {
    if (server.status !== 'connecting' && server.status !== 'needs_auth') return;
    const timer = setTimeout(() => { mcpService.get(server.id).then(setServer).catch(() => {}); }, 2000);
    return () => clearTimeout(timer);
  }, [server]);

  const act = async (action: () => Promise<McpServer | void>) => {
    setBusy(true);
    setError(null);
    try {
      const result = await action();
      if (result) {
        setServer(result);
        onChanged(result);
      } else {
        onChanged(null);
      }
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const toggleLogs = async () => {
    if (logs) { setLogs(null); return; }
    try {
      setLogs(await mcpService.logs(server.id));
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const testConnection = async () => {
    setCheck('running');
    try {
      setCheck(await mcpService.test(server.id));
    } catch (err) {
      setCheck({ ok: false, message: getErrorMessage(err) });
    }
  };

  const tools = [...server.tools, ...server.blocked_tools];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn('px-2 py-0.5 rounded text-xs font-medium', STATUS_STYLES[server.status])}>{server.status}</span>
        <code className="text-xs text-nexus-text-muted">{server.slug}__*</code>
        {server.status === 'connected' && <span className="text-xs text-nexus-text-muted">{server.tools.length} tool(s)</span>}
        <span className="flex-1" />
        {server.signed_in && server.status !== 'needs_auth' && (
          <Button variant="ghost" size="sm" disabled={busy}
            onClick={() => { if (window.confirm(`Sign out of ${server.name}? You'll need to sign in again to use it.`)) void act(() => mcpService.signOut(server.id)); }}>
            Sign out
          </Button>
        )}
        <label className="flex items-center gap-2 text-sm text-nexus-text-secondary">
          <input type="checkbox" checked={server.enabled} disabled={busy}
            onChange={(e) => void act(() => mcpService.update(server.id, { enabled: e.target.checked }))} />
          Enabled
        </label>
        <Button variant="ghost" size="sm" aria-label="Reconnect" disabled={busy || !server.enabled}
          onClick={() => void act(() => mcpService.restart(server.id))}>
          <RefreshCw className={cn('w-4 h-4', busy && 'animate-spin')} />
        </Button>
        <Button variant="secondary" size="sm" disabled={check === 'running'} onClick={() => void testConnection()}>
          {check === 'running' ? 'Testing…' : 'Test connection'}
        </Button>
        <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>Edit</Button>
        <Button variant="ghost" size="sm" aria-label="Remove server" className="text-nexus-danger"
          onClick={() => {
            if (window.confirm(`Remove ${server.name}? Workflows using its tools will fail.`)) void act(() => mcpService.remove(server.id));
          }}>
          <Trash2 className="w-4 h-4" />
        </Button>
      </div>

      <p className="text-xs text-nexus-text-muted truncate font-mono">
        {server.url}
      </p>
      {server.error && server.status !== 'connected' && server.status !== 'needs_auth' && <p className="text-xs text-nexus-danger">{server.error}</p>}
      {server.status === 'needs_auth' && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 space-y-2">
          <p className="text-sm text-nexus-text">One more step: sign in to {server.name} so Nexus can use it.</p>
          {server.auth_url ? (
            <a href={server.auth_url} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-nexus-accent text-nexus-bg text-sm font-medium hover:opacity-90">
              <LogIn className="w-4 h-4" /> Sign in to {server.name}
            </a>
          ) : <p className="text-xs text-nexus-text-muted">Preparing the sign-in page…</p>}
          <p className="text-xs text-nexus-text-muted">A new tab opens. When you finish there, this panel updates by itself.</p>
        </div>
      )}
      {server.status === 'connecting' && (
        <p className="text-xs text-nexus-text-muted">Connecting…</p>
      )}
      {error && <p role="alert" className="text-sm text-nexus-danger">{error}</p>}
      {check && check !== 'running' && (
        <p role="status" className={cn('text-sm', check.ok ? 'text-green-500' : 'text-nexus-danger')}>
          {check.ok ? '✓ ' : '✗ '}{check.message}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-nexus-text-muted">
        {server.health?.connected_since && <span>Connected {formatRelativeTime(server.health.connected_since)}</span>}
        {server.health && <span>{server.health.calls} call(s), {server.health.failures} failed</span>}
        {server.health?.last_call_at && <span>Last used {formatRelativeTime(server.health.last_call_at)}</span>}
        <button type="button" className="underline" onClick={() => void toggleLogs()}>{logs ? 'Hide logs' : 'Show logs'}</button>
      </div>
      {logs && (
        <div className="space-y-2">
          <ul className="text-xs text-nexus-text-secondary space-y-0.5 max-h-40 overflow-y-auto">
            {logs.events.length === 0 && <li className="text-nexus-text-muted">No connection events yet.</li>}
            {[...logs.events].reverse().map((event, i) => (
              <li key={i}><span className="text-nexus-text-muted font-mono">{event.at.replace('T', ' ').replace('Z', '')}</span> {event.message}</li>
            ))}
          </ul>
        </div>
      )}

      {tools.length === 0 ? (
        <p className="text-sm text-nexus-text-muted">No tools available{server.status !== 'connected' ? ' until the server connects' : ''}.</p>
      ) : (
        <>
          <p className="text-xs text-nexus-text-muted">
            Allow: runs without asking. Ask: the chat agent asks you first. Block: hidden from the agent and workflows.
          </p>
          <ul className="grid gap-2 sm:grid-cols-2">
            {tools.map(tool => (
              <li key={tool.name} className={cn('p-2 rounded border border-nexus-border', tool.policy === 'block' && 'opacity-60')}>
                <div className="flex items-center justify-between gap-2">
                  <code className="text-xs text-nexus-accent truncate">{tool.name}</code>
                  <select value={tool.policy} disabled={busy} aria-label={`Policy for ${tool.name}`}
                    onChange={(e) => void act(() => mcpService.update(server.id, {
                      tool_policies: { ...server.tool_policies, [tool.remote_name]: e.target.value as ToolPolicy },
                    }))}
                    className="px-1.5 py-0.5 rounded bg-nexus-bg-tertiary border border-nexus-border text-xs text-nexus-text">
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

      <ServerFormModal open={editing} server={server} onClose={() => setEditing(false)}
        onSaved={(saved) => { setEditing(false); setServer(saved); onChanged(saved); }} />
    </div>
  );
}
