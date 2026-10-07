import { useRef } from 'react';
import { cn } from '../../lib/utils';
import { DynamicContent } from './DynamicContent';
import type { ToolDefinition, WorkflowNode } from '../../types/workflow';
import type { LLMProviderConfig } from '../../types/llm';

/** What a template field can reference (used by the dynamic content picker). */
export interface DynamicSources {
  trigger: WorkflowNode | null;
  earlierSteps: WorkflowNode[];
  lastOutputs: Record<string, unknown>;
}

export const fieldClass =
  'w-full px-3 py-2 rounded-lg bg-nexus-bg-tertiary border border-nexus-border text-sm text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent';

export function FieldLabel({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <span className="block text-xs font-medium text-nexus-text-secondary mb-1">
      {children}
      {hint && <span className="ml-1 font-normal text-nexus-text-muted">{hint}</span>}
    </span>
  );
}

interface TemplateInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  multiline?: boolean;
  sources?: DynamicSources;
  mono?: boolean;
  label?: string;
}

/** A text field whose value may contain {{ }} references to earlier steps. */
export function TemplateInput({ value, onChange, placeholder, multiline, mono, label, sources }: TemplateInputProps) {
  const ref = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  const insert = (text: string) => {
    const el = ref.current;
    const start = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? value.length;
    onChange(value.slice(0, start) + text + value.slice(end));
  };
  const props = {
    ref,
    value,
    placeholder,
    'aria-label': label,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange(e.target.value),
    className: cn(fieldClass, mono && 'font-mono'),
  };
  const field = multiline ? <textarea rows={3} {...props} /> : <input {...props} />;
  if (!sources) return field;
  return (
    <div className="flex gap-1 items-stretch">
      <div className="flex-1 min-w-0">{field}</div>
      <DynamicContent sources={sources} onPick={insert} />
    </div>
  );
}

/** Turn typed text into the schema's type unless it is a {{ template }}. */
function parseTyped(text: string, type?: string): unknown {
  if (text.includes('{{')) return text;
  if ((type === 'integer' || type === 'number') && text.trim() !== '' && !Number.isNaN(Number(text))) return Number(text);
  if (type === 'boolean' && (text === 'true' || text === 'false')) return text === 'true';
  if ((type === 'object' || type === 'array') && /^[[{]/.test(text.trim())) {
    try { return JSON.parse(text); } catch { return text; }
  }
  return text;
}

interface ParameterFormProps {
  tool: ToolDefinition | undefined;
  parameters: Record<string, unknown>;
  onChange: (parameters: Record<string, unknown>) => void;
  sources?: DynamicSources;
}

export function ParameterForm({ tool, parameters, onChange, sources }: ParameterFormProps) {
  if (!tool) return null;
  const required = new Set(tool.parameters.required ?? []);
  const entries = Object.entries(tool.parameters.properties ?? {});
  if (entries.length === 0) return <p className="text-xs text-nexus-text-muted">This tool takes no parameters.</p>;
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {entries.map(([key, schema]) => {
        const raw = parameters[key];
        const value = raw === undefined || raw === null ? '' : typeof raw === 'string' ? raw : JSON.stringify(raw);
        return (
          <label key={key} className="block">
            <FieldLabel hint={required.has(key) ? '(required)' : schema.type ? `(${schema.type})` : undefined}>{key}</FieldLabel>
            <TemplateInput
              value={value}
              label={key}
              placeholder={schema.description ?? ''}
              sources={sources}
              onChange={(text) => onChange({ ...parameters, [key]: parseTyped(text, schema.type) })}
            />
          </label>
        );
      })}
    </div>
  );
}

const OPERATORS = [
  ['truthy', 'is true / present'], ['falsy', 'is false / missing'], ['equals', 'equals'], ['not_equals', 'does not equal'],
  ['contains', 'contains'], ['not_contains', 'does not contain'], ['gt', '>'], ['gte', '>='], ['lt', '<'], ['lte', '<='],
  ['is_empty', 'is empty'], ['not_empty', 'is not empty'],
] as const;

interface StepConfigProps {
  node: WorkflowNode;
  onConfig: (patch: Record<string, unknown>) => void;
  tools: Map<string, ToolDefinition>;
  llmProviders: LLMProviderConfig[];
  sources: DynamicSources;
}

/** The settings form shown when a step card is expanded. */
export function StepConfig({ node, onConfig, tools, llmProviders, sources }: StepConfigProps) {
  const c = node.config;
  switch (node.type) {
    case 'action': {
      const tool = tools.get(String(c.tool ?? ''));
      return (
        <div className="space-y-3">
          {!tool && (
            <p className="text-xs text-nexus-warning">
              The MCP server for <code>{String(c.tool ?? 'this tool')}</code> is not connected. Check it on the MCP Servers page.
            </p>
          )}
          <ParameterForm
            tool={tool}
            parameters={(c.parameters as Record<string, unknown>) ?? {}}
            onChange={(parameters) => onConfig({ parameters })}
            sources={sources}
          />
        </div>
      );
    }
    case 'llm':
      return (
        <div className="space-y-3">
          <label className="block">
            <FieldLabel>Prompt</FieldLabel>
            <TemplateInput multiline value={String(c.prompt ?? '')} onChange={(prompt) => onConfig({ prompt })}
              placeholder="Summarize this for a standup: {{ steps.action_1.text }}" sources={sources} label="Prompt" />
          </label>
          <label className="block">
            <FieldLabel>Model</FieldLabel>
            <select value={String(c.provider_id ?? '')} className={fieldClass}
              onChange={(e) => onConfig({ provider_id: e.target.value ? Number(e.target.value) : null })}>
              <option value="">Default provider</option>
              {llmProviders.filter(p => p.enabled).map(p => <option key={p.id} value={p.id}>{p.provider_name} · {p.model}</option>)}
            </select>
          </label>
          <p className="text-xs text-nexus-text-muted">The reply is available as <code>{`{{ steps.${node.id}.text }}`}</code>.</p>
        </div>
      );
    case 'condition': {
      const op = String(c.operator ?? 'truthy');
      const needsValue = !['truthy', 'falsy', 'is_empty', 'not_empty'].includes(op);
      return (
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block">
            <FieldLabel>Value to check</FieldLabel>
            <TemplateInput value={String(c.field ?? '')} onChange={(field) => onConfig({ field })}
              placeholder="steps.action_1.data.items" sources={sources} label="Value to check" />
          </label>
          <label className="block">
            <FieldLabel>Operator</FieldLabel>
            <select value={op} onChange={(e) => onConfig({ operator: e.target.value })} className={fieldClass}>
              {OPERATORS.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
            </select>
          </label>
          {needsValue && (
            <label className="block">
              <FieldLabel>Compare with</FieldLabel>
              <TemplateInput value={String(c.value ?? '')} onChange={(value) => onConfig({ value })} sources={sources} label="Compare with" />
            </label>
          )}
        </div>
      );
    }
    case 'transform':
    case 'output':
      return (
        <label className="block">
          <FieldLabel hint={node.type === 'output' ? '(optional; defaults to every step result)' : '(text or JSON)'}>Template</FieldLabel>
          <TemplateInput multiline mono value={String(c.template ?? '')} onChange={(template) => onConfig({ template })}
            placeholder={'{"count": {{ steps.action_1.data.items | length }}}'} sources={sources} label="Template" />
        </label>
      );
    case 'delay':
      return (
        <label className="block w-40">
          <FieldLabel>Seconds (max 300)</FieldLabel>
          <input type="number" min={0} max={300} value={Number(c.seconds ?? 5)} className={fieldClass}
            onChange={(e) => onConfig({ seconds: Number(e.target.value) })} />
        </label>
      );
    default:
      return null;
  }
}
