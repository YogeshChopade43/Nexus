import { useState } from 'react';
import { BookOpen, X } from 'lucide-react';
import { ragService } from '../../services/rag';
import { getErrorMessage } from '../../lib/utils';
import type { ChunkView, Citation } from '../../types/rag';

function label(c: Citation): string {
  return `[${c.n}] ${c.document_name}${c.pages ? ` · p. ${c.pages}` : ''}`;
}

/** The sources an answer cited, and a panel showing a cited passage in context. */
export function Sources({ citations }: { citations: Citation[] }) {
  const [open, setOpen] = useState<Citation | null>(null);
  const [view, setView] = useState<ChunkView | null>(null);
  const [error, setError] = useState<string | null>(null);

  const show = async (citation: Citation) => {
    setOpen(citation);
    setView(null);
    setError(null);
    try {
      setView(await ragService.chunk(citation.document_id, citation.chunk_id));
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };

  return (
    <div className="mt-2 text-left">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="flex items-center gap-1 text-xs text-nexus-text-muted"><BookOpen className="w-3.5 h-3.5" /> Sources</span>
        {citations.map(c => (
          <button key={c.n} type="button" onClick={() => void show(c)} title={c.snippet}
            className="px-2 py-0.5 rounded-full border border-nexus-border text-xs text-nexus-text-secondary hover:border-nexus-accent hover:text-nexus-text">
            {label(c)}
          </button>
        ))}
      </div>

      {open && (
        <div role="dialog" aria-label="Source" className="mt-2 rounded-lg border border-nexus-border bg-nexus-bg-tertiary/40 p-3 text-xs">
          <div className="flex items-start gap-2">
            <p className="flex-1 font-medium text-nexus-text">
              {label(open)}{open.heading_path && <span className="font-normal text-nexus-text-muted"> › {open.heading_path}</span>}
            </p>
            <button type="button" aria-label="Close source" onClick={() => setOpen(null)} className="text-nexus-text-muted hover:text-nexus-text">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
          {error && <p className="text-nexus-danger mt-1">{error}</p>}
          {!view && !error && <p className="text-nexus-text-muted mt-1">Loading…</p>}
          {view && (
            <div className="mt-1.5 space-y-1.5 max-h-72 overflow-y-auto whitespace-pre-line">
              {view.before && <p className="text-nexus-text-muted">{view.before.text}</p>}
              <p className="text-nexus-text bg-nexus-accent/10 border-l-2 border-nexus-accent pl-2">{view.chunk.text}</p>
              {view.after && <p className="text-nexus-text-muted">{view.after.text}</p>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
