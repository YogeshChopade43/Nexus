import { listApps } from '../../services/integrations';
import { useEffect, useState } from 'react';
import { Modal } from '../ui/Modal';
import { Button } from '../ui/Button';
import { ragService } from '../../services/rag';
import type { Library } from '../../types/rag';
import { getErrorMessage } from '../../lib/utils';
import type { McpServer } from '../../types/mcp';
import type { ChatSettings } from '../../types/chat';

interface Props {
  open: boolean;
  settings: ChatSettings;
  onSave: (settings: ChatSettings) => Promise<void>;
  onClose: () => void;
}

/** Options for this conversation only: which servers it may use, extra instructions, creativity. */
export function ChatSettingsModal({ open, settings, onSave, onClose }: Props) {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [draft, setDraft] = useState<ChatSettings>(settings);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDraft(settings);
    setError(null);
    listApps().then(setServers).catch(() => setServers([]));
    ragService.collections().then(setLibraries).catch(() => setLibraries([]));
  }, [open, settings]);

  const chosen = new Set(draft.servers ?? servers.map(s => s.slug));
  const toggle = (slug: string) => {
    const next = new Set(chosen);
    if (next.has(slug)) next.delete(slug); else next.add(slug);
    // Every server ticked means "all", which also covers servers added later.
    setDraft({ ...draft, servers: next.size === servers.length ? null : [...next] });
  };

  const save = async () => {
    try {
      await onSave(draft);
      onClose();
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Chat settings" size="lg">
      <div className="space-y-5">
        <section>
          <h3 className="text-sm font-medium text-nexus-text">Apps this chat can use</h3>
          <p className="text-xs text-nexus-text-muted mb-2">Fewer apps means faster, cheaper and more accurate tool choices. Document search and memory are always available.</p>
          {servers.length === 0 ? <p className="text-sm text-nexus-text-muted">No MCP servers yet.</p> : (
            <div className="grid gap-1 sm:grid-cols-2">
              {servers.map(server => (
                <label key={server.id} className="flex items-center gap-2 text-sm text-nexus-text">
                  <input type="checkbox" checked={chosen.has(server.slug)} onChange={() => toggle(server.slug)} />
                  {server.name}
                  {server.status !== 'connected' && <span className="text-xs text-nexus-text-muted">({server.status})</span>}
                </label>
              ))}
            </div>
          )}
        </section>

        <label className="block">
          <span className="block text-sm font-medium text-nexus-text">Answer from library</span>
          <span className="block text-xs text-nexus-text-muted mb-1">The library is searched for every message and answers cite it. Otherwise the agent searches all libraries when it needs to.</span>
          <select
            value={draft.library_id ?? ''}
            onChange={(e) => setDraft({ ...draft, library_id: e.target.value ? Number(e.target.value) : null })}
            className="w-full rounded-lg p-2 text-sm text-nexus-text bg-nexus-bg-tertiary border border-nexus-border focus:outline-none focus:ring-2 focus:ring-nexus-accent/25"
          >
            <option value="">None</option>
            {libraries.map(l => <option key={l.id} value={l.id}>{l.name} ({l.ready} documents)</option>)}
          </select>
        </label>

        <label className="block">
          <span className="block text-sm font-medium text-nexus-text">Instructions</span>
          <span className="block text-xs text-nexus-text-muted mb-1">Followed for every message in this chat, e.g. "Answer in French" or "Our team is called Atlas".</span>
          <textarea
            rows={4}
            maxLength={4000}
            value={draft.instructions}
            onChange={(e) => setDraft({ ...draft, instructions: e.target.value })}
            className="w-full rounded-lg p-2 text-sm text-nexus-text bg-nexus-bg-tertiary border border-nexus-border focus:outline-none focus:ring-2 focus:ring-nexus-accent/25"
          />
        </label>

        <section>
          <label className="flex items-center gap-2 text-sm font-medium text-nexus-text">
            <input type="checkbox" checked={draft.temperature !== null}
              onChange={(e) => setDraft({ ...draft, temperature: e.target.checked ? 0.7 : null })} />
            Set creativity (temperature)
          </label>
          {draft.temperature !== null && (
            <div className="flex items-center gap-3 mt-2">
              <span className="text-xs text-nexus-text-muted">Precise</span>
              <input type="range" min={0} max={1} step={0.1} value={draft.temperature} aria-label="Temperature"
                onChange={(e) => setDraft({ ...draft, temperature: Number(e.target.value) })} className="flex-1" />
              <span className="text-xs text-nexus-text-muted">Creative</span>
              <span className="text-xs text-nexus-text w-8 text-right">{draft.temperature.toFixed(1)}</span>
            </div>
          )}
        </section>

        {error && <p className="text-sm text-nexus-danger" role="alert">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={() => void save()}>Save</Button>
        </div>
      </div>
    </Modal>
  );
}
