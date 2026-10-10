import { useEffect, useState } from 'react';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';
import { cn, getErrorMessage } from '../../lib/utils';
import { mcpService } from '../../services/mcp';
import { parseMcpConfig } from '../servers/catalog';
import { inputClass } from './ServerFormModal';

/** Add the servers from another app's MCP config file (Claude Desktop, Claude Code, Cursor, VS Code). */
export function ImportModal({ open, onClose, onImported }: { open: boolean; onClose: () => void; onImported: () => void }) {
  const [text, setText] = useState('');
  const [result, setResult] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {  // a fresh start each time it opens
    if (!open) return;
    setText('');
    setResult(null);
  }, [open]);

  const importConfig = async () => {
    setResult(null);
    let parsed: ReturnType<typeof parseMcpConfig>;
    try {
      parsed = parseMcpConfig(text);
    } catch (err) {
      setResult(`Could not read that file: ${getErrorMessage(err)}`);
      return;
    }
    // Nexus connects to hosted servers only: commands it would have to run on this computer are skipped.
    const hosted = parsed.servers.filter(server => server.transport === 'http');
    const local = parsed.servers.filter(server => server.transport !== 'http')
      .map(server => `${server.name}: runs on this computer; Nexus uses hosted servers only (find it in the Marketplace)`);
    setBusy(true);
    const results = await Promise.allSettled(hosted.map(server => mcpService.create(server)));
    setBusy(false);
    const failed = results.flatMap((r, i) => (r.status === 'rejected' ? [`${hosted[i].name}: ${getErrorMessage(r.reason)}`] : []));
    const added = results.length - failed.length;
    setResult([`Added ${added} server(s).`, ...failed.map(f => `Failed ${f}`),
      ...[...local, ...parsed.skipped].map(s => `Skipped ${s}`)].join('\n'));
    if (added) onImported();
  };

  return (
    <Modal open={open} onClose={() => !busy && onClose()} title="Import MCP servers" size="lg">
      <div className="space-y-3">
        <p className="text-sm text-nexus-text-secondary">
          Paste or choose a config file from Claude Desktop (<code>claude_desktop_config.json</code>), Claude Code
          (<code>.mcp.json</code> or <code>~/.claude.json</code>), Cursor or VS Code (<code>.vscode/mcp.json</code>).
        </p>
        <input type="file" accept=".json,application/json" aria-label="Choose a config file"
          onChange={(e) => { const file = e.target.files?.[0]; if (file) void file.text().then(setText); }}
          className="text-sm text-nexus-text-secondary" />
        <textarea rows={8} value={text} onChange={(e) => setText(e.target.value)} aria-label="Config file contents"
          placeholder='{"mcpServers": {"linear": {"type": "http", "url": "https://mcp.linear.app/mcp"}}}'
          className={cn(inputClass, 'font-mono text-xs')} />
        {result && <pre className="text-sm text-nexus-text-secondary whitespace-pre-wrap" role="status">{result}</pre>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>Close</Button>
          <Button variant="primary" onClick={() => void importConfig()} loading={busy} disabled={busy || !text.trim()}>
            {busy ? 'Connecting…' : 'Import'}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
