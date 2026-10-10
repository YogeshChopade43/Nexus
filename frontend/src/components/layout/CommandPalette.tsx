import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AppWindow, FileText, GitBranch, LayoutGrid, MessageSquare, Search } from 'lucide-react';
import { cn } from '../../lib/utils';
import { chatService } from '../../services/chat';
import { mcpService } from '../../services/mcp';
import { ragService } from '../../services/rag';
import { workflowService } from '../../services/workflow';

type Kind = 'Page' | 'Chat' | 'Workflow' | 'App' | 'Document';

interface Result {
  kind: Kind;
  label: string;
  /** Where it goes: a path, or a chat to open. */
  to?: string;
  chat?: string;
}

const ICONS = { Page: LayoutGrid, Chat: MessageSquare, Workflow: GitBranch, App: AppWindow, Document: FileText };

/** Pages and settings, with the words people search them by. */
const PAGES: (Result & { keywords: string })[] = [
  { kind: 'Page', label: 'Agent chat', to: '/', keywords: 'chat agent ask conversation' },
  { kind: 'Page', label: 'Workflows', to: '/workflows', keywords: 'workflows automations schedules reminders' },
  { kind: 'Page', label: 'Marketplace', to: '/servers', keywords: 'marketplace apps mcp servers connect install' },
  { kind: 'Page', label: 'Knowledge', to: '/knowledge', keywords: 'knowledge documents files library memory' },
  { kind: 'Page', label: 'Dashboard', to: '/dashboard', keywords: 'dashboard usage cost tokens' },
  { kind: 'Page', label: 'Activity', to: '/activity', keywords: 'activity history log' },
  { kind: 'Page', label: 'Settings: General', to: '/settings', keywords: 'settings general theme timezone retention' },
  { kind: 'Page', label: 'Settings: AI provider', to: '/settings?tab=ai', keywords: 'settings ai provider model llm api key' },
];

const MAX_PER_KIND = 5;
export const OPEN_SEARCH_EVENT = 'nexus:search';

const matches = (text: string, query: string) => query.split(/\s+/).every(word => text.toLowerCase().includes(word));

/** Ctrl+K / Cmd+K: find any page, setting, chat, workflow, app or document and go there. */
export function CommandPalette({ onOpenChat }: { onOpenChat: (sessionId: string) => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const [items, setItems] = useState<Result[]>([]);  // workflows, apps and documents: loaded when opened
  const [chats, setChats] = useState<Result[]>([]);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen(o => !o);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener('keydown', onKey);
    window.addEventListener(OPEN_SEARCH_EVENT, onOpen);
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener(OPEN_SEARCH_EVENT, onOpen); };
  }, []);

  useEffect(() => {
    if (!open) return;
    setQuery('');
    setActive(0);
    requestAnimationFrame(() => inputRef.current?.focus());
    const workflows = workflowService.getWorkflows()
      .then(list => list.map(w => ({ kind: 'Workflow' as const, label: w.name, to: `/workflows?open=${w.id}` })))
      .catch(() => [] as Result[]);
    const apps = mcpService.list()
      .then(list => list.map(s => ({ kind: 'App' as const, label: s.name, to: '/servers' })))
      .catch(() => [] as Result[]);
    const documents = ragService.collections()
      .then(libraries => Promise.all(libraries.filter(l => l.kind === 'library').map(l => ragService.documents(l.id))))
      .then(lists => lists.flat().map(d => ({ kind: 'Document' as const, label: d.name, to: '/knowledge' })))
      .catch(() => [] as Result[]);
    void Promise.all([workflows, apps, documents]).then(groups => setItems(groups.flat()));
  }, [open]);

  // Chats are searched by the server (titles and message text), debounced.
  useEffect(() => {
    if (!open) return;
    const timer = setTimeout(() => {
      chatService.listSessions(query.trim())
        .then(list => setChats(list.map(s => ({ kind: 'Chat' as const, label: s.title || 'Untitled chat', chat: s.session_id }))))
        .catch(() => setChats([]));
    }, 200);
    return () => clearTimeout(timer);
  }, [open, query]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    const pages = PAGES.filter(p => !q || matches(`${p.label} ${p.keywords}`, q));
    const found = items.filter(i => q && matches(i.label, q));
    const byKind = (kind: Kind, list: Result[]) => list.filter(r => r.kind === kind).slice(0, MAX_PER_KIND);
    return [...byKind('App', found), ...byKind('Chat', chats), ...byKind('Workflow', found), ...byKind('Document', found),
      ...pages.slice(0, q ? MAX_PER_KIND : PAGES.length)];
  }, [query, items, chats]);

  if (!open) return null;

  const go = (result: Result) => {
    setOpen(false);
    if (result.chat) {
      navigate('/');
      onOpenChat(result.chat);
    } else if (result.to) {
      navigate(result.to);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (results.length) setActive(i => (i + (e.key === 'ArrowDown' ? 1 : results.length - 1)) % results.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const chosen = results[active] ?? results[0];
      if (chosen) go(chosen);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setOpen(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-start justify-center p-4 pt-[12vh] bg-black/50" onMouseDown={() => setOpen(false)}>
      <div role="dialog" aria-label="Search" onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-lg rounded-xl border border-nexus-border bg-nexus-bg-secondary shadow-2xl overflow-hidden">
        <div className="flex items-center gap-2 px-3 border-b border-nexus-border">
          <Search className="w-4 h-4 text-nexus-text-muted" aria-hidden />
          <input ref={inputRef} role="combobox" aria-label="Search Nexus" aria-expanded aria-controls="palette-results"
            value={query} onChange={(e) => { setQuery(e.target.value); setActive(0); }} onKeyDown={onKeyDown}
            placeholder="Search chats, workflows, apps, documents, settings…"
            className="flex-1 py-3 bg-transparent text-sm text-nexus-text placeholder-nexus-text-muted focus:outline-none" />
          <kbd className="text-[10px] text-nexus-text-muted border border-nexus-border rounded px-1">Esc</kbd>
        </div>
        <ul id="palette-results" role="listbox" aria-label="Results" className="max-h-80 overflow-y-auto py-1">
          {results.length === 0 && <li className="px-3 py-6 text-center text-sm text-nexus-text-muted">Nothing found.</li>}
          {results.map((result, i) => {
            const Icon = ICONS[result.kind];
            return (
              <li key={`${result.kind}-${result.label}-${i}`} role="option" aria-selected={i === active}
                onMouseEnter={() => setActive(i)} onClick={() => go(result)}
                className={cn('flex items-center gap-2.5 px-3 py-2 text-sm cursor-pointer',
                  i === active ? 'bg-nexus-bg-tertiary text-nexus-text' : 'text-nexus-text-secondary')}>
                <span className="w-16 text-xs text-nexus-text-muted flex items-center gap-1"><Icon className="w-3.5 h-3.5" aria-hidden />{result.kind}</span>
                <span className="truncate">{result.label}</span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
