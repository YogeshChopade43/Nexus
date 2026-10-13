import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from '../../lib/utils';
import { ToolName } from './ToolName';
import { FileChip } from './FilePreview';
import type { AgentEvent, FileRef } from '../../types/chat';

const MAX_RAW = 6000;  // characters of a raw result shown inline

/** A file a tool made (Create file): the tool's own data sits under the result's ``data``. */
function fileOf(event: AgentEvent): FileRef | null {
  const result = event.data as { data?: { file?: FileRef } } | undefined;
  return result?.data?.file ?? null;
}

/** Files a reply made: preview or download each. */
export function MadeFiles({ events }: { events: AgentEvent[] }) {
  const made = events.map(fileOf).filter((f): f is FileRef => f !== null);
  if (made.length === 0) return null;
  return <div className="mt-3 flex flex-wrap gap-2">{made.map(file => <FileChip key={file.id} file={file} />)}</div>;
}

/** "From your apps": each tool call an answer was built from, with what was asked and what came back. */
export function ToolSources({ events }: { events: AgentEvent[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (events.length === 0) return null;
  const shown = open !== null ? events[open] : null;
  const raw = shown ? JSON.stringify(shown.data ?? {}, null, 2) : '';
  const args = shown && shown.arguments && typeof shown.arguments === 'object' ? Object.entries(shown.arguments as Record<string, unknown>) : [];

  return (
    <section aria-label="Sources from your apps" className="mt-3">
      <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wider text-nexus-text-muted">From your apps</p>
      <div className="flex flex-wrap gap-1.5">
        {events.map((event, index) => (
          <button key={index} type="button" aria-expanded={open === index} onClick={() => setOpen(open === index ? null : index)}
            className={cn('inline-flex max-w-full items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors',
              open === index ? 'border-nexus-accent/50 bg-nexus-accent/5' : 'border-nexus-border bg-nexus-bg-secondary hover:border-nexus-border-hover')}>
            <ToolName name={String(event.tool_name ?? '')} />
            {event.summary ? <span className="truncate text-nexus-text-muted">· {String(event.summary)}</span> : null}
            <ChevronDown className={cn('h-3 w-3 shrink-0 text-nexus-text-muted transition-transform', open === index && 'rotate-180')} aria-hidden />
          </button>
        ))}
      </div>
      {shown && (
        <div className="mt-2 space-y-2 rounded-lg border border-nexus-border bg-nexus-bg-secondary p-3 text-xs">
          {args.length > 0 && (
            <div>
              <p className="mb-1 font-medium text-nexus-text-secondary">Nexus asked with</p>
              <ul className="space-y-0.5 text-nexus-text-secondary">
                {args.map(([key, value]) => <li key={key}><span className="text-nexus-text-muted">{key}:</span> {typeof value === 'string' ? value : JSON.stringify(value)}</li>)}
              </ul>
            </div>
          )}
          <div>
            <p className="mb-1 font-medium text-nexus-text-secondary">The app returned</p>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-nexus-bg-tertiary/50 p-2 font-mono text-[11px] text-nexus-text-secondary">
              {raw.length > MAX_RAW ? `${raw.slice(0, MAX_RAW)}\n… (${raw.length - MAX_RAW} more characters)` : raw}
            </pre>
          </div>
        </div>
      )}
    </section>
  );
}
