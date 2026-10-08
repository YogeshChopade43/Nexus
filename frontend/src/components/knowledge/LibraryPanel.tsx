import { useCallback, useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react';
import { FileText, Pencil, RotateCcw, Search, Trash2, Upload } from 'lucide-react';
import { Button } from '../ui/Button';
import { cn, formatRelativeTime, getErrorMessage } from '../../lib/utils';
import { ragService, settled } from '../../services/rag';
import type { Library, Passage, RagDocument } from '../../types/rag';

export const ACCEPT = '.pdf,.docx,.xlsx,.txt,.md,.csv,.json,.html,.htm,.log,.yaml,.yml,.xml,text/*,application/pdf';
const inputClass =
  'w-full px-3 py-2 rounded-lg bg-nexus-bg-tertiary border border-nexus-border text-sm text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent';

function StatusBadge({ doc }: { doc: RagDocument }) {
  const styles: Record<string, string> = {
    ready: 'bg-green-500/15 text-green-500',
    failed: 'bg-red-500/15 text-red-500',
    processing: 'bg-blue-500/15 text-blue-500',
    queued: 'bg-gray-500/15 text-nexus-text-muted',
  };
  const label = doc.status === 'processing' ? `Processing ${doc.progress}%` : doc.status === 'queued' ? 'Queued'
    : doc.status === 'ready' ? 'Ready' : 'Failed';
  return <span className={cn('px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap', styles[doc.status])}>{label}</span>;
}

function pages(p: Passage): string {
  if (p.page_start === null) return '';
  return p.page_end && p.page_end !== p.page_start ? ` · pages ${p.page_start}–${p.page_end}` : ` · page ${p.page_start}`;
}

interface Props {
  library: Library;
  onChanged: () => void;
  onDeleted: () => void;
  pollMs?: number;
}

/** One library: its documents with live processing status, uploads, and a test search. */
export function LibraryPanel({ library, onChanged, onDeleted, pollMs = 2000 }: Props) {
  const [documents, setDocuments] = useState<RagDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<Passage[] | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setDocuments(await ragService.documents(library.id));
    } catch (err) {
      setError(getErrorMessage(err));
    }
  }, [library.id]);

  useEffect(() => {
    setDocuments(null);
    setHits(null);
    void load();
  }, [load]);

  // Keep refreshing while anything is still being processed.
  const busy = documents?.some(d => !settled(d)) ?? false;
  useEffect(() => {
    if (!busy) return;
    const timer = setTimeout(() => void load().then(onChanged), pollMs);
    return () => clearTimeout(timer);
  }, [busy, documents, load, onChanged, pollMs]);

  const act = async (action: () => Promise<unknown>) => {
    setError(null);
    try {
      await action();
      await load();
      onChanged();
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const upload = async (files: File[]) => {
    if (!files.length) return;
    setUploading(true);
    await act(() => ragService.upload(library.id, files));
    setUploading(false);
    if (fileRef.current) fileRef.current.value = '';
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    void upload(Array.from(event.dataTransfer.files));
  };

  const search = async (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim()) return;
    try {
      setHits((await ragService.search(query.trim(), [library.id])).sources);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  const rename = () => {
    const name = window.prompt('Rename library', library.name);
    if (name && name.trim() && name !== library.name) void act(() => ragService.renameCollection(library.id, name.trim()));
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="flex-1 text-lg font-semibold text-nexus-text">{library.name}</h3>
        <Button variant="ghost" size="sm" onClick={rename} aria-label={`Rename ${library.name}`}><Pencil className="w-4 h-4" /></Button>
        <Button variant="ghost" size="sm" className="text-nexus-danger" aria-label={`Delete ${library.name}`}
          onClick={() => {
            if (window.confirm(`Delete the library "${library.name}" and all its documents?`)) {
              void ragService.deleteCollection(library.id).then(onDeleted).catch(err => setError(getErrorMessage(err)));
            }
          }}>
          <Trash2 className="w-4 h-4" />
        </Button>
      </div>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn('rounded-lg border-2 border-dashed p-4 text-center text-sm transition-colors',
          dragging ? 'border-nexus-accent bg-nexus-accent/5' : 'border-nexus-border')}
      >
        <input ref={fileRef} type="file" multiple hidden accept={ACCEPT}
          onChange={(e) => void upload(Array.from(e.target.files ?? []))} />
        <p className="text-nexus-text-secondary">Drop files here, or</p>
        <Button variant="secondary" size="sm" className="gap-1.5 mt-2" loading={uploading} disabled={uploading}
          onClick={() => fileRef.current?.click()}>
          <Upload className="w-4 h-4" /> Add documents
        </Button>
        <p className="text-xs text-nexus-text-muted mt-2">PDF (with selectable text), Word, Excel, Markdown, CSV, HTML or text, up to 25 MB each.</p>
      </div>

      {error && <p className="text-sm text-nexus-danger whitespace-pre-line" role="alert">{error}</p>}

      {documents === null ? <p className="text-sm text-nexus-text-muted">Loading…</p> : documents.length === 0 ? (
        <p className="text-sm text-nexus-text-muted">No documents in this library yet.</p>
      ) : (
        <ul className="divide-y divide-nexus-border">
          {documents.map(doc => (
            <li key={doc.id} className="py-2.5 flex items-start gap-3">
              <FileText className="w-4 h-4 mt-0.5 text-nexus-text-muted flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm text-nexus-text truncate">{doc.name}</span>
                  {doc.version > 1 && <span className="text-xs text-nexus-text-muted">v{doc.version}</span>}
                  <StatusBadge doc={doc} />
                </div>
                <p className="text-xs text-nexus-text-muted">
                  {doc.status === 'ready'
                    ? `${doc.chunk_count} passages${doc.pages ? ` · ${doc.pages} pages` : ''} · added ${formatRelativeTime(doc.created_at)}`
                    : `added ${formatRelativeTime(doc.created_at)}`}
                </p>
                {doc.error && (
                  <p className={cn('text-xs mt-0.5', doc.status === 'failed' ? 'text-nexus-danger' : 'text-amber-500')}>{doc.error}</p>
                )}
              </div>
              {doc.status === 'failed' && (
                <Button variant="ghost" size="sm" aria-label={`Retry ${doc.name}`} title="Try again"
                  onClick={() => void act(() => ragService.retryDocument(doc.id))}>
                  <RotateCcw className="w-4 h-4" />
                </Button>
              )}
              <Button variant="ghost" size="sm" className="text-nexus-danger" aria-label={`Remove ${doc.name}`}
                onClick={() => { if (window.confirm(`Remove ${doc.name}?`)) void act(() => ragService.deleteDocument(doc.id)); }}>
                <Trash2 className="w-4 h-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}

      {documents && documents.some(d => d.status === 'ready') && (
        <form onSubmit={(e) => void search(e)} className="space-y-2">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-nexus-text-muted" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Try a search: what would the agent find?"
              aria-label="Search this library" className={`${inputClass} pl-8`} />
          </div>
          {hits && (hits.length === 0 ? <p className="text-sm text-nexus-text-muted">Nothing found.</p> : (
            <ol className="space-y-2">
              {hits.map((hit, i) => (
                <li key={hit.chunk_id} className="p-2.5 rounded-lg bg-nexus-bg-tertiary/50 text-xs">
                  <p className="font-medium text-nexus-text">
                    {i + 1}. {hit.document_name}{hit.heading_path && ` › ${hit.heading_path}`}{pages(hit)}
                    <span className="ml-2 font-normal text-nexus-text-muted">relevance {hit.score.toFixed(2)}</span>
                  </p>
                  <p className="text-nexus-text-secondary mt-1 line-clamp-4 whitespace-pre-line">{hit.text}</p>
                </li>
              ))}
            </ol>
          ))}
        </form>
      )}
    </div>
  );
}
