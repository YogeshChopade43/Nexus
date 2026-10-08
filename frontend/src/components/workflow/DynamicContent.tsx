import { useState } from 'react';
import { Zap } from 'lucide-react';
import type { ManualInput, WorkflowNode } from '../../types/workflow';
import type { DynamicSources } from './StepConfig';

export interface DynamicEntry {
  group: string;
  label: string;
  path: string;
}

const MAX_KEYS = 30;

function keysOf(value: unknown): string[] {
  return value && typeof value === 'object' && !Array.isArray(value) ? Object.keys(value).slice(0, MAX_KEYS) : [];
}

/** Everything a field can reference, given the trigger, the steps before it, and the last run's outputs. */
export function dynamicEntries({ trigger, earlierSteps, lastOutputs, scopes = [] }: DynamicSources): DynamicEntry[] {
  const entries: DynamicEntry[] = [];
  if (scopes.includes('loop')) {
    entries.push({ group: 'Current loop', label: 'Current item', path: 'loop.item' }, { group: 'Current loop', label: 'Item number (from 0)', path: 'loop.index' });
  }
  if (scopes.includes('error')) {
    entries.push({ group: 'Error', label: 'Error message', path: 'error.message' });
  }
  if (trigger) {
    const type = String(trigger.config.trigger_type ?? 'manual');
    if (type === 'manual') {
      for (const input of (trigger.config.inputs as ManualInput[] | undefined) ?? []) {
        entries.push({ group: 'Trigger', label: input.name, path: `trigger.inputs.${input.name}` });
      }
    } else if (type === 'poll') {
      entries.push({ group: 'Trigger', label: 'New item', path: 'trigger.item' });
      const lastItem = (lastOutputs.__trigger as { item?: unknown } | undefined)?.item;
      for (const key of keysOf(lastItem)) entries.push({ group: 'Trigger', label: `item.${key}`, path: `trigger.item.${key}` });
    } else if (type === 'webhook' || type === 'app_event') {
      entries.push({ group: 'Trigger', label: 'Request body', path: 'trigger.payload' });
    } else {
      entries.push({ group: 'Trigger', label: 'Time it ran', path: 'trigger.fired_at' });
    }
  }
  for (const node of earlierSteps) {
    entries.push(...stepEntries(node, lastOutputs[node.id]));
  }
  return entries;
}

function stepEntries(node: WorkflowNode, output: unknown): DynamicEntry[] {
  const base = `steps.${node.id}`;
  const group = node.name || node.id;
  switch (node.type) {
    case 'action': {
      const entries = [
        { group, label: 'Result text', path: `${base}.text` },
        { group, label: 'Result data', path: `${base}.data` },
      ];
      const data = (output as { data?: unknown } | undefined)?.data;
      for (const key of keysOf(data)) entries.push({ group, label: `data.${key}`, path: `${base}.data.${key}` });
      return entries;
    }
    case 'llm':
      return [{ group, label: 'AI reply', path: `${base}.text` }];
    case 'transform':
      return [{ group, label: 'Composed value', path: `${base}.value` }];
    case 'condition':
      return [{ group, label: 'Condition result', path: `${base}.result` }];
    case 'http':
      return [{ group, label: 'Status code', path: `${base}.status` }, { group, label: 'Response data', path: `${base}.data` }];
    case 'code':
      return [{ group, label: 'Returned value', path: `${base}.value` }];
    case 'workflow':
      return [{ group, label: 'Workflow result', path: `${base}.result` }];
    case 'loop':
      return [{ group, label: 'All results', path: `${base}.results` }, { group, label: 'Item count', path: `${base}.count` }];
    case 'parallel':
      return [{ group, label: 'Branch results', path: `${base}.branches` }];
    default:
      return [];
  }
}

interface DynamicContentProps {
  sources: DynamicSources;
  onPick: (text: string) => void;
}

/** The ⚡ button next to a field: lists earlier outputs and inserts {{ path }}. */
export function DynamicContent({ sources, onPick }: DynamicContentProps) {
  const [open, setOpen] = useState(false);
  const entries = dynamicEntries(sources);
  const groups = [...new Set(entries.map(e => e.group))];
  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen(v => !v)} aria-label="Insert dynamic content" aria-expanded={open}
        title="Insert data from the trigger or earlier steps"
        className="h-full px-2 rounded-lg border border-nexus-border text-nexus-accent hover:bg-nexus-accent-dim">
        <Zap className="w-4 h-4" />
      </button>
      {open && (
        <div role="listbox" aria-label="Dynamic content"
          className="absolute right-0 z-30 mt-1 w-72 max-h-72 overflow-y-auto rounded-lg border border-nexus-border bg-nexus-bg-secondary shadow-lg p-2">
          {entries.length === 0 ? (
            <p className="text-xs text-nexus-text-muted p-1">Nothing to insert yet. Add a trigger input or a step above this one.</p>
          ) : groups.map(group => (
            <div key={group} className="mb-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-nexus-text-muted px-1">{group}</p>
              {entries.filter(e => e.group === group).map(entry => (
                <button key={entry.path} role="option" aria-selected={false} type="button"
                  onClick={() => { onPick(`{{ ${entry.path} }}`); setOpen(false); }}
                  className="w-full text-left px-2 py-1 rounded text-xs hover:bg-nexus-bg-tertiary">
                  <span className="text-nexus-text">{entry.label}</span>
                  <code className="block text-[10px] text-nexus-text-muted">{entry.path}</code>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
