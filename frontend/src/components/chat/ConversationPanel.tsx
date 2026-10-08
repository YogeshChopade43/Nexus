import { useEffect, useState } from 'react';
import { Search, Trash2, X } from 'lucide-react';
import { cn, formatRelativeTime } from '../../lib/utils';
import type { AgentSession } from '../../types/chat';

interface Props {
  sessions: AgentSession[];
  currentId: string | null;
  onSearch: (query: string) => void;
  onOpen: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  onClose: () => void;
}

/** Past conversations, searchable by title and message text. */
export function ConversationPanel({ sessions, currentId, onSearch, onOpen, onDelete, onClose }: Props) {
  const [query, setQuery] = useState('');

  // Search as you type, without a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => onSearch(query.trim()), 250);
    return () => clearTimeout(timer);
  }, [query, onSearch]);

  return (
    <div className="absolute right-4 top-16 z-20 w-80 max-w-[calc(100%-2rem)] rounded-xl border border-nexus-border bg-nexus-bg-secondary shadow-lg"
      role="dialog" aria-label="Conversations">
      <div className="p-2 flex items-center gap-2 border-b border-nexus-border">
        <div className="relative flex-1">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-nexus-text-muted" />
          <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search conversations"
            aria-label="Search conversations"
            className="w-full pl-8 pr-2 py-1.5 rounded-lg bg-nexus-bg-tertiary border border-nexus-border text-sm text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent" />
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="text-nexus-text-muted hover:text-nexus-text"><X className="w-4 h-4" /></button>
      </div>
      <ul className="max-h-96 overflow-y-auto p-1">
        {sessions.length === 0 && <li className="p-3 text-sm text-nexus-text-muted">{query ? 'No conversations match.' : 'No conversations yet.'}</li>}
        {sessions.map(s => (
          <li key={s.session_id} className="group flex items-center">
            <button type="button" onClick={() => onOpen(s.session_id)}
              className={cn('flex-1 min-w-0 text-left px-2.5 py-2 rounded-lg hover:bg-nexus-bg-tertiary', s.session_id === currentId && 'bg-nexus-accent-dim')}>
              <span className="block text-sm text-nexus-text truncate">{s.title || 'Untitled conversation'}</span>
              <span className="block text-xs text-nexus-text-muted">{formatRelativeTime(s.updated_at)}</span>
            </button>
            <button type="button" aria-label={`Delete ${s.title || 'conversation'}`}
              onClick={() => { if (window.confirm('Delete this conversation?')) onDelete(s.session_id); }}
              className="p-2 text-nexus-text-muted hover:text-nexus-danger opacity-0 group-hover:opacity-100 focus:opacity-100">
              <Trash2 className="w-4 h-4" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
