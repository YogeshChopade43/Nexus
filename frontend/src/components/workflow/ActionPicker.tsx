import { NodeTile } from './NodeTile';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown, ChevronRight, Search, X } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { McpServer, McpTool } from '../../types/mcp';
import type { WorkflowNodeType } from '../../types/workflow';
import { paramLabel, toolKind, toolLabel, toolSummary } from './toolInfo';

export type PickedAction =
  | { type: Exclude<WorkflowNodeType, 'trigger' | 'action' | 'output'>; name: string }
  | { type: 'action'; name: string; tool: string };

export const BUILT_INS: Array<{ type: Exclude<WorkflowNodeType, 'trigger' | 'action' | 'output'>; name: string; description: string }> = [
  { type: 'llm', name: 'AI prompt', description: 'Ask the language model to write, summarize or decide' },
  { type: 'condition', name: 'Condition', description: 'Do different things depending on a value' },
  { type: 'transform', name: 'Compose', description: 'Build text or JSON from earlier steps' },
  { type: 'delay', name: 'Delay', description: 'Wait before continuing' },
  { type: 'loop', name: 'For each', description: 'Repeat steps for every item in a list' },
  { type: 'parallel', name: 'Parallel branches', description: 'Run several sets of steps at the same time' },
  { type: 'http', name: 'HTTP request', description: 'Call any web API (GET, POST, …)' },
  { type: 'code', name: 'Code (JavaScript)', description: 'Reshape data with a small sandboxed script' },
  { type: 'workflow', name: 'Run a workflow', description: 'Call another workflow and use its result' },
];

interface ActionPickerProps {
  servers: McpServer[];
  onPick: (action: PickedAction) => void;
  onClose: () => void;
  /** Only list app tools (used by the polling trigger). */
  toolsOnly?: boolean;
  /** Built-in steps to leave out (ones that need the canvas, like branches, in a simple list of steps). */
  without?: WorkflowNodeType[];
}

interface ToolEntry {
  tool: McpTool;
  label: string;
  summary: string;
  kind: 'read' | 'write';
}

function entries(server: McpServer): ToolEntry[] {
  return server.tools
    .map(tool => ({ tool, label: toolLabel(tool), summary: toolSummary(tool), kind: toolKind(tool) }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

function ToolButton({ entry, onPick }: { entry: ToolEntry; onPick: () => void }) {
  const needs = (entry.tool.required ?? []).map(paramLabel);
  return (
    <button
      type="button"
      onClick={onPick}
      title={entry.tool.remote_name}
      className="w-full text-left px-2.5 py-2 rounded-md hover:bg-nexus-bg-tertiary focus:outline-none focus:ring-2 focus:ring-nexus-accent/25"
    >
      <span className="block text-sm text-nexus-text">{entry.label}</span>
      {entry.summary && <span className="block text-xs text-nexus-text-muted line-clamp-2 mt-0.5">{entry.summary}</span>}
      {needs.length > 0 && (
        <span className="block text-[11px] text-nexus-text-muted mt-0.5">Needs: {needs.slice(0, 4).join(', ')}{needs.length > 4 ? '…' : ''}</span>
      )}
    </button>
  );
}

export function ActionPicker({ servers, onPick, onClose, toolsOnly, without = [] }: ActionPickerProps) {
  const [query, setQuery] = useState('');
  // With several apps, start collapsed so the list is a short menu of apps.
  const [open, setOpen] = useState<Set<number>>(() => new Set(servers.length <= 1 ? servers.map(s => s.id) : []));
  const q = query.trim().toLowerCase();
  const matches = (...texts: string[]) => !q || texts.some(t => t.toLowerCase().includes(q));

  const builtIns = toolsOnly ? [] : BUILT_INS.filter(b => !without.includes(b.type) && matches(b.name, b.description));
  const toggle = (id: number) => setOpen(prev => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  return (
    <div className="rounded-lg border border-nexus-border bg-nexus-bg-secondary shadow-pop p-3 space-y-3" role="dialog" aria-label="Choose an operation">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-nexus-text-muted" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={toolsOnly ? 'Search app operations' : 'Search apps and actions'}
            aria-label={toolsOnly ? 'Search app operations' : 'Search apps and actions'}
            className="w-full pl-8 pr-3 py-2 rounded-lg bg-nexus-bg-tertiary border border-nexus-border text-sm text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent/25"
          />
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="text-nexus-text-muted hover:text-nexus-text"><X className="w-4 h-4" /></button>
      </div>

      <div className="max-h-96 overflow-y-auto space-y-3">
        {builtIns.length > 0 && (
          <section>
            <h5 className="text-xs font-semibold uppercase tracking-wide text-nexus-text-muted mb-1">Built-in</h5>
            <div className="grid gap-1 sm:grid-cols-2">
              {builtIns.map(b => (
                <button key={b.type} type="button" onClick={() => onPick({ type: b.type, name: b.name })} className="text-left p-2 rounded hover:bg-nexus-bg-tertiary">
                  <div className="flex items-center gap-2 text-[13px] font-medium text-nexus-text"><NodeTile type={b.type} size="sm" /> {b.name}</div>
                  <div className="text-xs text-nexus-text-muted">{b.description}</div>
                </button>
              ))}
            </div>
          </section>
        )}

        {servers.map(server => {
          const connected = server.status === 'connected';
          const all = entries(server);
          const shown = all.filter(e => matches(server.name, e.label, e.summary, e.tool.remote_name));
          if (q && shown.length === 0) return null;
          const expanded = !!q || open.has(server.id);
          // Reads first: most steps, and every poll trigger, start by fetching something.
          const groups: Array<[string, ToolEntry[]]> = [
            ['Reads', shown.filter(e => e.kind === 'read')],
            ['Changes data', shown.filter(e => e.kind === 'write')],
          ];
          return (
            <section key={server.id} className="rounded-lg border border-nexus-border">
              <button
                type="button"
                onClick={() => toggle(server.id)}
                aria-expanded={expanded}
                className="w-full flex items-center gap-2 px-3 py-2 text-left"
              >
                {expanded ? <ChevronDown className="w-4 h-4 text-nexus-text-muted" /> : <ChevronRight className="w-4 h-4 text-nexus-text-muted" />}
                <span className="text-sm font-medium text-nexus-text">{server.name}</span>
                <span className="text-xs text-nexus-text-muted">
                  {q ? `${shown.length} of ${all.length}` : `${all.length} action${all.length === 1 ? '' : 's'}`}
                </span>
                {!connected && <span className="ml-auto text-xs text-amber-500">{server.status}</span>}
              </button>
              {expanded && (
                <div className="px-2 pb-2">
                  {!connected && (
                    <p className="px-1 pb-2 text-xs text-nexus-text-muted">
                      Not connected, so its actions can't be added. <Link to="/servers" className="underline">Check the Marketplace</Link>
                    </p>
                  )}
                  <div className={cn(!connected && 'opacity-50 pointer-events-none')}>
                    {all.length === 0 && connected && <p className="px-1 text-xs text-nexus-text-muted">This server has no tools.</p>}
                    {groups.map(([title, list]) => list.length > 0 && (
                      <div key={title} className="mt-1">
                        <h6 className="px-2.5 text-[11px] font-semibold uppercase tracking-wide text-nexus-text-muted">{title}</h6>
                        <div className="grid sm:grid-cols-2">
                          {list.map(entry => (
                            <ToolButton key={entry.tool.name} entry={entry}
                              onPick={() => onPick({ type: 'action', name: entry.label, tool: entry.tool.name })} />
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>
          );
        })}

        {servers.length === 0 && (
          <p className="text-xs text-nexus-text-muted">
            No apps yet. <Link to="/servers" className="underline">Add an MCP server</Link> to use its tools here.
          </p>
        )}
      </div>
    </div>
  );
}
