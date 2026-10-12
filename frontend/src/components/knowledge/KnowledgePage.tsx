import { fieldClass as inputClass } from '../ui/Input';
import { PageHeader } from '../ui/PageHeader';
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { BookOpen, Brain, Loader2, Plus, Trash2 } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/Card';
import { Button } from '../ui/Button';
import { cn, getErrorMessage } from '../../lib/utils';
import { knowledgeService } from '../../services/knowledge';
import { ragService } from '../../services/rag';
import { settingsService } from '../../services/settings';
import { LibraryPanel } from './LibraryPanel';
import type { Memory } from '../../types/knowledge';
import type { Library, RagStatus } from '../../types/rag';


export function KnowledgePage() {
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [newName, setNewName] = useState('');
  const [status, setStatus] = useState<RagStatus | null>(null);
  const [rerank, setRerank] = useState(true);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [fact, setFact] = useState('');
  const [error, setError] = useState<string | null>(null);

  const loadLibraries = useCallback(async () => {
    try {
      const list = await ragService.collections();
      setLibraries(list);
      setSelected(current => (current !== null && list.some(l => l.id === current) ? current : list[0]?.id ?? null));
    } catch (err) {
      setError(getErrorMessage(err));
    }
  }, []);

  useEffect(() => {
    void loadLibraries();
    knowledgeService.memories().then(setMemories).catch(err => setError(getErrorMessage(err)));
    settingsService.getSettings().then(s => setRerank(s.user.ragRerank !== false)).catch(() => {});
  }, [loadLibraries]);

  // The first upload downloads the local search models; show that instead of an unexplained wait.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const poll = () => ragService.status().then(s => {
      setStatus(s);
      if (!s.models_ready && (s.queue.queued + s.queue.running + s.queue.retry) > 0) timer = setTimeout(poll, 3000);
    }).catch(() => {});
    void poll();
    return () => clearTimeout(timer);
  }, [libraries]);

  const createLibrary = async (event: FormEvent) => {
    event.preventDefault();
    if (!newName.trim()) return;
    try {
      const library = await ragService.createCollection(newName.trim());
      setNewName('');
      await loadLibraries();
      setSelected(library.id);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const toggleRerank = (on: boolean) => {
    setRerank(on);
    settingsService.updateUserSettings({ ragRerank: on }).catch(err => { setRerank(!on); setError(getErrorMessage(err)); });
  };

  const memoryAction = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
      setMemories(await knowledgeService.memories());
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const current = libraries.find(l => l.id === selected) ?? null;
  const waiting = status && !status.models_ready && (status.queue.queued + status.queue.running + status.queue.retry) > 0;

  return (
    <div className="space-y-6 max-w-5xl">
      <PageHeader title="Knowledge" description="Libraries of documents the agent searches and cites, and facts it remembers across chats." />
      {error && <p className="text-sm text-nexus-danger whitespace-pre-line" role="alert">{error}</p>}
      {waiting && (
        <p className="flex items-center gap-2 text-sm text-nexus-text-secondary rounded-lg border border-nexus-border p-3" role="status">
          <Loader2 className="w-4 h-4 animate-spin text-nexus-accent-text" />
          Preparing the search model (first time only, about 220 MB). Your documents will be processed right after.
        </p>
      )}

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2"><BookOpen className="w-5 h-5" /> Libraries</CardTitle>
              <CardDescription>Group documents by topic. In chat, the agent searches all libraries, or you can attach one in Chat settings to answer only from it.</CardDescription>
            </div>
            <label className="flex items-center gap-2 text-sm text-nexus-text-secondary" title="Re-scores search results with a local model: more accurate, slightly slower">
              <input type="checkbox" checked={rerank} onChange={(e) => toggleRerank(e.target.checked)} />
              Rerank results
            </label>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-6 md:grid-cols-[14rem_1fr]">
            <div className="space-y-2">
              <ul className="space-y-1" aria-label="Libraries">
                {libraries.map(library => (
                  <li key={library.id}>
                    <button type="button" onClick={() => setSelected(library.id)} aria-current={library.id === selected}
                      className={cn('w-full text-left px-3 py-2 rounded-lg text-sm',
                        library.id === selected ? 'bg-nexus-accent-dim text-nexus-accent-text' : 'text-nexus-text-secondary hover:bg-nexus-bg-tertiary')}>
                      <span className="block truncate">{library.name}</span>
                      <span className="block text-xs text-nexus-text-muted">{library.ready} of {library.documents} ready</span>
                    </button>
                  </li>
                ))}
              </ul>
              <form onSubmit={(e) => void createLibrary(e)} className="flex gap-1.5">
                <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="New library" maxLength={100}
                  aria-label="New library name" className={inputClass} />
                <Button type="submit" variant="secondary" size="sm" className="h-9 w-9 shrink-0 px-0" aria-label="Create library" disabled={!newName.trim()}>
                  <Plus className="w-4 h-4" />
                </Button>
              </form>
            </div>
            <div className="min-w-0">
              {current ? (
                <LibraryPanel key={current.id} library={current} onChanged={() => void loadLibraries()}
                  onDeleted={() => { setSelected(null); void loadLibraries(); }} />
              ) : (
                <p className="text-sm text-nexus-text-muted">Create a library to add documents.</p>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Brain className="w-5 h-5" /> Memory</CardTitle>
          <CardDescription>Facts the agent keeps in mind in every chat. It saves one when you say "remember …", or add them here.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {memories.length === 0 ? <p className="text-sm text-nexus-text-muted">Nothing remembered yet.</p> : (
            <ul className="divide-y divide-nexus-border">
              {memories.map(memory => (
                <li key={memory.id} className="py-2 flex items-center gap-3">
                  <span className="flex-1 text-sm text-nexus-text">{memory.content}</span>
                  <Button variant="ghost" size="sm" aria-label={`Forget: ${memory.content}`} className="text-nexus-danger"
                    onClick={() => void memoryAction(() => knowledgeService.removeMemory(memory.id))}>
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <form className="flex gap-2" onSubmit={(e) => {
            e.preventDefault();
            if (fact.trim()) void memoryAction(async () => { await knowledgeService.addMemory(fact.trim()); setFact(''); });
          }}>
            <input value={fact} onChange={(e) => setFact(e.target.value)} maxLength={500} placeholder="e.g. My main Notion database is Roadmap"
              aria-label="New memory" className={inputClass} />
            <Button type="submit" variant="secondary" size="sm" disabled={!fact.trim()}>Add</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
