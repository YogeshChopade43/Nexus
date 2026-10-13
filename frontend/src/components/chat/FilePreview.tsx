import { useEffect, useState } from 'react';
import { Download, FileText } from 'lucide-react';
import { api } from '../../services/api';
import { cn, getErrorMessage } from '../../lib/utils';
import { Modal } from '../ui/Modal';
import { Markdown } from './Markdown';
import type { FileRef } from '../../types/chat';

type Preview =
  | { kind: 'table'; sheets: { name: string; rows: (string | number)[][]; truncated: boolean }[] }
  | { kind: 'markdown' | 'text' | 'html'; text: string; truncated: boolean }
  | { kind: 'pdf' | 'none' };

export const fileSize = (bytes: number) =>
  (bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} KB` : `${(bytes / 1048576).toFixed(1)} MB`);

const href = (file: FileRef) => `${api.getBaseUrl()}${file.url}`;

/** A file in the chat (attached or made): click to preview, or download it. */
export function FileChip({ file }: { file: FileRef }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="inline-flex max-w-full items-stretch overflow-hidden rounded-lg border border-nexus-border bg-nexus-bg-secondary text-left shadow-surface transition-colors hover:border-nexus-border-hover">
      <button type="button" onClick={() => setOpen(true)} aria-label={`Preview ${file.name}`}
        className="flex min-w-0 items-center gap-2.5 px-3 py-2 hover:bg-nexus-bg-tertiary/40">
        <FileText className="h-4 w-4 shrink-0 text-nexus-text-muted" aria-hidden />
        <span className="min-w-0">
          <span className="block truncate text-[13px] font-medium text-nexus-text">{file.name}</span>
          <span className="block text-[11px] text-nexus-text-muted">{fileSize(file.size)}</span>
        </span>
      </button>
      <a href={href(file)} download={file.name} aria-label={`Download ${file.name}`}
        className="flex items-center border-l border-nexus-border px-2.5 text-nexus-text-muted transition-colors hover:bg-nexus-bg-tertiary/40 hover:text-nexus-accent-text">
        <Download className="h-4 w-4" aria-hidden />
      </a>
      {open && <FilePreview file={file} onClose={() => setOpen(false)} />}
    </span>
  );
}

function Table({ rows }: { rows: (string | number)[][] }) {
  const [head, ...body] = rows;
  return (
    <table className="w-full border-collapse text-[13px]">
      {head && (
        <thead className="sticky top-0 bg-nexus-bg-tertiary">
          <tr>{head.map((cell, i) => <th key={i} className="border border-nexus-border px-2 py-1.5 text-left font-semibold text-nexus-text">{String(cell)}</th>)}</tr>
        </thead>
      )}
      <tbody>
        {body.map((row, r) => (
          <tr key={r} className="even:bg-nexus-bg-tertiary/30">
            {row.map((cell, c) => (
              <td key={c} className={cn('border border-nexus-border px-2 py-1 text-nexus-text-secondary', typeof cell === 'number' && 'text-right tabular-nums')}>
                {String(cell)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const More = ({ show }: { show: boolean }) =>
  show ? <p className="mt-2 text-xs text-nexus-text-muted">Showing the beginning only: download the file to see all of it.</p> : null;

export function FilePreview({ file, onClose }: { file: FileRef; onClose: () => void }) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sheet, setSheet] = useState(0);

  useEffect(() => {
    api.get<Preview>(`${file.url}/preview`).then(setPreview, err => setError(getErrorMessage(err)));
  }, [file.url]);

  let body;
  if (error) body = <p className="text-sm text-nexus-danger">Couldn&apos;t open it: {error}. The file may have been cleaned up.</p>;
  else if (!preview) body = <p className="text-sm text-nexus-text-muted">Loading preview…</p>;
  else if (preview.kind === 'table') {
    const shown = preview.sheets[sheet] ?? preview.sheets[0];
    body = (
      <>
        {preview.sheets.length > 1 && (
          <div role="tablist" className="mb-2 flex flex-wrap gap-1">
            {preview.sheets.map((s, i) => (
              <button key={s.name} type="button" role="tab" aria-selected={i === sheet} onClick={() => setSheet(i)}
                className={cn('rounded-md px-2.5 py-1 text-xs', i === sheet ? 'bg-nexus-accent/10 text-nexus-accent-text' : 'text-nexus-text-secondary hover:bg-nexus-bg-tertiary')}>
                {s.name}
              </button>
            ))}
          </div>
        )}
        {shown && shown.rows.length ? <div className="max-h-[65vh] overflow-auto"><Table rows={shown.rows} /></div>
          : <p className="text-sm text-nexus-text-muted">This sheet is empty.</p>}
        <More show={!!shown?.truncated} />
      </>
    );
  } else if (preview.kind === 'markdown') {
    body = <div className="max-h-[65vh] overflow-auto"><Markdown text={preview.text} /><More show={preview.truncated} /></div>;
  } else if (preview.kind === 'text') {
    body = (
      <>
        <pre className="max-h-[65vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-nexus-bg-tertiary/50 p-3 font-mono text-xs text-nexus-text-secondary">{preview.text}</pre>
        <More show={preview.truncated} />
      </>
    );
  } else if (preview.kind === 'html') {
    // sandbox="" : no scripts, no forms, no access to Nexus; the page only gets drawn.
    body = <iframe title={file.name} sandbox="" srcDoc={preview.text} className="h-[65vh] w-full rounded-lg border border-nexus-border bg-white" />;
  } else if (preview.kind === 'pdf') {
    body = <iframe title={file.name} src={`${href(file)}?inline=1`} className="h-[70vh] w-full rounded-lg border border-nexus-border" />;
  } else {
    body = <p className="text-sm text-nexus-text-secondary">There&apos;s no preview for this kind of file. Download it to open it.</p>;
  }

  return (
    <Modal open onClose={onClose} title={file.name} description={fileSize(file.size)} size="xl">
      {body}
      <div className="mt-4 flex justify-end">
        <a href={href(file)} download={file.name}
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-nexus-border px-3 text-[13px] font-medium text-nexus-text hover:bg-nexus-bg-tertiary hover:no-underline">
          <Download className="h-3.5 w-3.5" aria-hidden /> Download
        </a>
      </div>
    </Modal>
  );
}
