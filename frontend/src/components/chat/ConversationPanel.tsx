import { useEffect, useRef, useState } from 'react';
import { Download, MoreHorizontal, Pencil, Pin, PinOff, Search, Trash2, X } from 'lucide-react';
import { cn, formatRelativeTime, getErrorMessage } from '../../lib/utils';
import { chatService } from '../../services/chat';
import { Dropdown } from '../ui/Dropdown';
import type { AgentSession } from '../../types/chat';

interface Props {
  sessions: AgentSession[];
  currentId: string | null;
  onSearch: (query: string) => void;
  onOpen: (sessionId: string) => void;
  onDelete: (sessionId: string) => Promise<void>;
  onClose: () => void;
}

const nameOf = (s: AgentSession) => s.title || 'Untitled conversation';

/** A conversation as a Markdown document: its title, then each message under who said it. */
export function toMarkdown(session: AgentSession): string {
  const body = session.messages
    .filter(m => m.content.trim())
    .map(m => `**${m.role === 'user' ? 'You' : 'Nexus'}:**\n\n${m.content.trim()}`)
    .join('\n\n');
  return `# ${nameOf(session)}\n\n${body}\n`;
}

async function exportMarkdown(id: string) {
  const session = await chatService.getSession(id);
  const url = URL.createObjectURL(new Blob([toMarkdown(session)], { type: 'text/markdown' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `${nameOf(session).replace(/[^\w\- ]+/g, '').trim().slice(0, 60) || 'conversation'}.md`;
  link.click();
  URL.revokeObjectURL(url);
}

/** Past conversations: search, open, rename, pin, export and delete (one or several). */
export function ConversationPanel({ sessions, currentId, onSearch, onOpen, onDelete, onClose }: Props) {
  const [query, setQuery] = useState('');
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);
  const [selected, setSelected] = useState<Set<string> | null>(null);  // null: not selecting
  const [error, setError] = useState<string | null>(null);
  const cancelRename = useRef(false);  // Escape: the blur that follows must not save

  // Search as you type, without a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => onSearch(query.trim()), 250);
    return () => clearTimeout(timer);
  }, [query, onSearch]);

  const run = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
      onSearch(query.trim());  // reload the list, keeping the search
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const saveTitle = () => {
    if (!renaming) return;
    const { id, title } = renaming;
    setRenaming(null);
    if (cancelRename.current) { cancelRename.current = false; return; }
    if (title.trim()) void run(() => chatService.updateSession(id, { title: title.trim() }));
  };

  const deleteSelected = async () => {
    if (!selected?.size || !window.confirm(`Delete ${selected.size} conversation(s)?`)) return;
    for (const id of selected) await onDelete(id);
    setSelected(null);
  };

  const toggle = (id: string) => setSelected(prev => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  return (
    <div className="absolute right-4 top-16 z-20 w-80 max-w-[calc(100%-2rem)] rounded-xl border border-nexus-border bg-nexus-bg-secondary shadow-pop"
      role="dialog" aria-label="Conversations">
      <div className="p-2 flex items-center gap-2 border-b border-nexus-border">
        <div className="relative flex-1">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-nexus-text-muted" />
          <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search conversations"
            aria-label="Search conversations"
            className="w-full pl-8 pr-2 py-1.5 rounded-lg bg-nexus-bg-tertiary border border-nexus-border text-sm text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent/25" />
        </div>
        <button type="button" onClick={() => setSelected(s => (s ? null : new Set()))}
          className="text-xs text-nexus-text-secondary hover:text-nexus-text">{selected ? 'Cancel' : 'Select'}</button>
        <button type="button" onClick={onClose} aria-label="Close" className="text-nexus-text-muted hover:text-nexus-text"><X className="w-4 h-4" /></button>
      </div>
      {error && <p role="alert" className="px-3 pt-2 text-xs text-nexus-danger">{error}</p>}
      <ul className="max-h-96 overflow-y-auto p-1">
        {sessions.length === 0 && <li className="p-3 text-sm text-nexus-text-muted">{query ? 'No conversations match.' : 'No conversations yet.'}</li>}
        {sessions.map(s => {
          const pinned = Boolean(s.metadata?.pinned);
          return (
            <li key={s.session_id} className="group flex items-center">
              {selected && (
                <input type="checkbox" className="ml-2" aria-label={`Select ${nameOf(s)}`}
                  checked={selected.has(s.session_id)} onChange={() => toggle(s.session_id)} />
              )}
              {renaming?.id === s.session_id ? (
                <input autoFocus value={renaming.title} aria-label="Conversation title"
                  onChange={(e) => setRenaming({ id: s.session_id, title: e.target.value })}
                  onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); if (e.key === 'Escape') { cancelRename.current = true; e.currentTarget.blur(); } }}
                  onBlur={saveTitle}
                  className="flex-1 min-w-0 mx-1 px-2 py-1.5 rounded-lg bg-nexus-bg-tertiary border border-nexus-border text-sm text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent/25" />
              ) : (
                <button type="button" onClick={() => (selected ? toggle(s.session_id) : onOpen(s.session_id))}
                  className={cn('flex-1 min-w-0 text-left px-2.5 py-2 rounded-lg hover:bg-nexus-bg-tertiary', s.session_id === currentId && 'bg-nexus-accent-dim')}>
                  <span className="flex items-center gap-1.5 text-sm text-nexus-text">
                    {pinned && <Pin role="img" aria-label="Pinned" className="w-3 h-3 shrink-0 text-nexus-accent-text" />}
                    <span className="truncate">{nameOf(s)}</span>
                  </span>
                  <span className="block text-xs text-nexus-text-muted">{formatRelativeTime(s.updated_at)}</span>
                </button>
              )}
              {!selected && (
                <Dropdown items={[
                  { label: 'Rename', icon: <Pencil className="w-4 h-4" />, onClick: () => setRenaming({ id: s.session_id, title: s.title }) },
                  { label: pinned ? 'Unpin' : 'Pin', icon: pinned ? <PinOff className="w-4 h-4" /> : <Pin className="w-4 h-4" />,
                    onClick: () => void run(() => chatService.updateSession(s.session_id, { pinned: !pinned })) },
                  { label: 'Export as Markdown', icon: <Download className="w-4 h-4" />,
                    onClick: () => void exportMarkdown(s.session_id).catch(err => setError(getErrorMessage(err))) },
                  { label: 'Delete', icon: <Trash2 className="w-4 h-4" />, danger: true,
                    onClick: () => { if (window.confirm('Delete this conversation?')) void onDelete(s.session_id); } },
                ]} trigger={
                  <button type="button" aria-label={`More actions for ${nameOf(s)}`}
                    className="p-2 text-nexus-text-muted hover:text-nexus-text opacity-0 group-hover:opacity-100 focus:opacity-100">
                    <MoreHorizontal className="w-4 h-4" />
                  </button>
                } />
              )}
            </li>
          );
        })}
      </ul>
      {selected && (
        <div className="p-2 border-t border-nexus-border flex justify-end">
          <button type="button" disabled={!selected.size} onClick={() => void deleteSelected()}
            className="px-3 py-1.5 rounded-lg text-sm bg-nexus-danger text-white disabled:opacity-50">
            Delete {selected.size}
          </button>
        </div>
      )}
    </div>
  );
}
