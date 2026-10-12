import { useRef, useState, type ReactNode } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Check, Copy, Download } from 'lucide-react';

/** Cells of a rendered table, for copying or saving. */
function tableRows(table: HTMLTableElement | null): string[][] {
  return table ? [...table.rows].map(row => [...row.cells].map(cell => cell.innerText.trim())) : [];
}

export function toCsv(rows: string[][]): string {
  return rows.map(row => row.map(cell => (/[",\n]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell)).join(',')).join('\n');
}

function CopyButton({ getText, label }: { getText: () => string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={() => navigator.clipboard.writeText(getText()).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }).catch(() => {})}
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] text-nexus-text-muted hover:text-nexus-text hover:bg-nexus-bg-tertiary"
    >
      {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}{copied ? 'Copied' : 'Copy'}
    </button>
  );
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const ref = useRef<HTMLPreElement>(null);
  const language = /language-(\w+)/.exec(String((children as { props?: { className?: string } })?.props?.className ?? ''))?.[1];
  return (
    <div className="my-2 rounded-lg border border-nexus-border bg-nexus-bg-tertiary/60 overflow-hidden">
      <div className="flex items-center justify-between px-2 py-1 border-b border-nexus-border">
        <span className="text-[11px] text-nexus-text-muted">{language ?? 'code'}</span>
        <CopyButton label="Copy code" getText={() => ref.current?.innerText ?? ''} />
      </div>
      <pre ref={ref} className="p-3 overflow-x-auto text-xs leading-relaxed">{children}</pre>
    </div>
  );
}

function Table({ children }: { children?: ReactNode }) {
  const ref = useRef<HTMLTableElement>(null);
  const download = () => {
    const blob = new Blob([toCsv(tableRows(ref.current))], { type: 'text/csv' });
    const link = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: 'table.csv' });
    link.click();
    URL.revokeObjectURL(link.href);
  };
  return (
    <div className="my-2">
      <div className="overflow-x-auto rounded-lg border border-nexus-border">
        <table ref={ref} className="w-full text-xs border-collapse">{children}</table>
      </div>
      <div className="flex gap-1 mt-1">
        {/* Tab-separated pastes straight into spreadsheet cells. */}
        <CopyButton label="Copy table" getText={() => tableRows(ref.current).map(r => r.join('\t')).join('\n')} />
        <button type="button" onClick={download} aria-label="Download table as CSV"
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] text-nexus-text-muted hover:text-nexus-text hover:bg-nexus-bg-tertiary">
          <Download className="w-3.5 h-3.5" />CSV
        </button>
      </div>
    </div>
  );
}

const components: Components = {
  pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
  table: ({ children }) => <Table>{children}</Table>,
  th: ({ children }) => <th className="px-2 py-1.5 text-left font-semibold border-b border-nexus-border bg-nexus-bg-tertiary/60">{children}</th>,
  td: ({ children }) => <td className="px-2 py-1.5 border-b border-nexus-border align-top">{children}</td>,
  a: ({ children, href }) => <a href={href} target="_blank" rel="noreferrer" className="text-nexus-accent-text underline">{children}</a>,
  code: ({ children, className }) => className
    ? <code className={className}>{children}</code>
    : <code className="px-1 py-0.5 rounded bg-nexus-bg-tertiary text-[0.85em]">{children}</code>,
  ul: ({ children }) => <ul className="list-disc pl-5 my-1.5 space-y-0.5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-5 my-1.5 space-y-0.5">{children}</ol>,
  h1: ({ children }) => <h3 className="text-base font-semibold mt-3 mb-1">{children}</h3>,
  h2: ({ children }) => <h3 className="text-base font-semibold mt-3 mb-1">{children}</h3>,
  h3: ({ children }) => <h4 className="text-sm font-semibold mt-2 mb-1">{children}</h4>,
  p: ({ children }) => <p className="my-1.5 first:mt-0 last:mb-0">{children}</p>,
  blockquote: ({ children }) => <blockquote className="border-l-2 border-nexus-border pl-3 text-nexus-text-secondary my-2">{children}</blockquote>,
  hr: () => <hr className="my-3 border-nexus-border" />,
};

/** Assistant replies as Markdown (GitHub flavour: tables, task lists). Raw HTML is not rendered. */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="text-sm break-words">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>{text}</ReactMarkdown>
    </div>
  );
}
