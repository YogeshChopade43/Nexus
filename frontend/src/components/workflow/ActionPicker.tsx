import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Search, X } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { McpServer } from '../../types/mcp';
import type { WorkflowNodeType } from '../../types/workflow';

export type PickedAction =
  | { type: Exclude<WorkflowNodeType, 'trigger' | 'action' | 'output'>; name: string }
  | { type: 'action'; name: string; tool: string };

export const BUILT_INS: Array<{ type: Exclude<WorkflowNodeType, 'trigger' | 'action' | 'output'>; name: string; description: string; icon: string }> = [
  { type: 'llm', name: 'AI prompt', description: 'Ask the language model to write, summarize or decide', icon: '✨' },
  { type: 'condition', name: 'Condition', description: 'Do different things depending on a value', icon: '🔀' },
  { type: 'transform', name: 'Compose', description: 'Build text or JSON from earlier steps', icon: '🔄' },
  { type: 'delay', name: 'Delay', description: 'Wait before continuing', icon: '⏱️' },
];

interface ActionPickerProps {
  servers: McpServer[];
  onPick: (action: PickedAction) => void;
  onClose: () => void;
  /** Only list app tools (used by the polling trigger). */
  toolsOnly?: boolean;
}

export function ActionPicker({ servers, onPick, onClose, toolsOnly }: ActionPickerProps) {
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();
  const matches = (...texts: string[]) => !q || texts.some(t => t.toLowerCase().includes(q));

  const builtIns = toolsOnly ? [] : BUILT_INS.filter(b => matches(b.name, b.description));

  return (
    <div className="rounded-lg border border-nexus-border bg-nexus-bg-secondary shadow-lg p-3 space-y-3" role="dialog" aria-label="Choose an operation">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-nexus-text-muted" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={toolsOnly ? 'Search app operations' : 'Search apps and actions'}
            className="w-full pl-8 pr-3 py-2 rounded-lg bg-nexus-bg-tertiary border border-nexus-border text-sm text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent"
          />
        </div>
        <button onClick={onClose} aria-label="Close" className="text-nexus-text-muted hover:text-nexus-text"><X className="w-4 h-4" /></button>
      </div>

      <div className="max-h-80 overflow-y-auto space-y-3">
        {builtIns.length > 0 && (
          <section>
            <h5 className="text-xs font-semibold uppercase tracking-wide text-nexus-text-muted mb-1">Built-in</h5>
            <div className="grid gap-1 sm:grid-cols-2">
              {builtIns.map(b => (
                <button key={b.type} onClick={() => onPick({ type: b.type, name: b.name })} className="text-left p-2 rounded hover:bg-nexus-bg-tertiary">
                  <div className="text-sm text-nexus-text">{b.icon} {b.name}</div>
                  <div className="text-xs text-nexus-text-muted">{b.description}</div>
                </button>
              ))}
            </div>
          </section>
        )}

        {servers.map(server => {
          const connected = server.status === 'connected';
          const tools = server.tools.filter(t => matches(server.name, t.remote_name, t.description));
          if (q && tools.length === 0) return null;
          return (
            <section key={server.id}>
              <h5 className="text-xs font-semibold uppercase tracking-wide text-nexus-text-muted mb-1 flex items-center gap-2">
                {server.name}
                {!connected && (
                  <span className="normal-case font-normal">
                    · {server.status} — <Link to="/servers" className="underline">check MCP Servers</Link>
                  </span>
                )}
              </h5>
              <div className={cn('grid gap-1 sm:grid-cols-2', !connected && 'opacity-50 pointer-events-none')}>
                {tools.map(tool => (
                  <button key={tool.name} onClick={() => onPick({ type: 'action', name: tool.remote_name, tool: tool.name })}
                    className="text-left p-2 rounded hover:bg-nexus-bg-tertiary">
                    <div className="text-sm text-nexus-text">{tool.remote_name}</div>
                    <div className="text-xs text-nexus-text-muted line-clamp-2">{tool.description.replace(`[${server.name}] `, '')}</div>
                  </button>
                ))}
              </div>
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
