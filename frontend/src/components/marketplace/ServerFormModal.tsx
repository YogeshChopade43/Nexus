import { useEffect, useState } from 'react';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';
import { cn, getErrorMessage } from '../../lib/utils';
import { mcpService } from '../../services/mcp';
import type { McpServer, McpServerInput } from '../../types/mcp';

export const inputClass =
  'w-full px-3 py-2 rounded-lg bg-nexus-bg-tertiary border border-nexus-border text-sm text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent';

/** "Name: value" lines <-> object. Masked values ("***") round-trip so stored secrets are kept. */
function fromLines(text: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const line of text.split('\n')) {
    const index = line.indexOf(':');
    if (index > 0) result[line.slice(0, index).trim()] = line.slice(index + 1).trim();
  }
  return result;
}

const toLines = (headers: Record<string, string>) => Object.entries(headers).map(([k, v]) => `${k}: ${v}`).join('\n');

/** Add a hosted server by URL (one that isn't in the Marketplace), or edit an installed server's address. */
export function ServerFormModal({ open, server, onClose, onSaved }: {
  open: boolean;
  /** null adds a new server. */
  server: McpServer | null;
  onClose: () => void;
  onSaved: (server: McpServer) => void;
}) {
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [headers, setHeaders] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(server?.name ?? '');
    setUrl(server?.url ?? '');
    setHeaders(toLines(server?.headers ?? {}));
    setError(null);
  }, [open, server]);

  const submit = async () => {
    const input: McpServerInput = { name: name.trim(), transport: 'http', url: url.trim(), headers: fromLines(headers) };
    setBusy(true);
    setError(null);
    try {
      onSaved(server ? await mcpService.update(server.id, input) : await mcpService.create(input));
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={() => !busy && onClose()} title={server ? 'Edit MCP server' : 'Add custom server'} size="lg">
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <label className="block">
          <span className="block text-xs font-medium text-nexus-text-secondary mb-1">Name</span>
          <input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Linear" className={inputClass} />
        </label>
        <label className="block">
          <span className="block text-xs font-medium text-nexus-text-secondary mb-1">Server URL</span>
          <input required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://mcp.linear.app/mcp" className={cn(inputClass, 'font-mono')} />
        </label>
        <label className="block">
          <span className="block text-xs font-medium text-nexus-text-secondary mb-1">Headers (one "Name: value" per line, stored encrypted)</span>
          <textarea rows={2} value={headers} onChange={(e) => setHeaders(e.target.value)} placeholder="Authorization: Bearer ..." className={cn(inputClass, 'font-mono')} />
        </label>
        <p className="text-xs text-nexus-text-muted">
          Nexus connects to hosted MCP servers. Servers that use sign-in ask you to sign in after saving; leave the headers empty for those.
        </p>
        {server && <p className="text-xs text-nexus-text-muted">Values shown as *** are kept unchanged.</p>}
        {error && <p className="text-sm text-nexus-danger" role="alert">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button type="submit" variant="primary" loading={busy} disabled={busy}>{busy ? 'Connecting…' : 'Save & connect'}</Button>
        </div>
      </form>
    </Modal>
  );
}
