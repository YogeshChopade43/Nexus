import { useRef } from 'react';
import { cn } from '../../lib/utils';
import { DynamicContent } from './DynamicContent';
import { paramFields, type ParamField } from './toolInfo';
import type { ToolDefinition, WorkflowNode } from '../../types/workflow';
import type { LLMProviderConfig } from '../../types/llm';

/** What a template field can reference (used by the dynamic content picker). */
export interface DynamicSources {
  trigger: WorkflowNode | null;
  earlierSteps: WorkflowNode[];
  lastOutputs: Record<string, unknown>;
  /** Extra scopes available where this field lives: inside a loop body or an error handler. */
  scopes?: Array<'loop' | 'error'>;
}

/** JSON object fields: stored objects show as JSON text; text that isn't valid JSON yet stays text. */
function JsonField({ value, onChange, placeholder, label }: { value: unknown; onChange: (v: unknown) => void; placeholder?: string; label: string }) {
  const text = value === undefined || value === null ? '' : typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  return (
    <textarea rows={3} aria-label={label} value={text} placeholder={placeholder} className={cn(fieldClass, 'font-mono')}
      onChange={(e) => {
        const raw = e.target.value;
        try { onChange(raw.trim() ? JSON.parse(raw) : undefined); } catch { onChange(raw); }
      }} />
  );
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
  const fields = paramFields(tool.parameters);
  if (fields.length === 0) return <p className="text-xs text-nexus-text-muted">This action takes no inputs.</p>;
  const required = fields.filter(f => f.required);
  const optional = fields.filter(f => !f.required);
  const isSet = (f: ParamField) => parameters[f.key] !== undefined && parameters[f.key] !== '';
  const setCount = optional.filter(isSet).length;
  const render = (f: ParamField) => (
    <ParamInput key={f.key} field={f} value={parameters[f.key]} sources={sources}
      onChange={(value) => {
        const next = { ...parameters };
        if (value === undefined || value === '') delete next[f.key]; else next[f.key] = value;
        onChange(next);
      }} />
  );
  return (
    <div className="space-y-3">
      {required.length > 0 && <div className="grid gap-3 sm:grid-cols-2">{required.map(render)}</div>}
      {optional.length > 0 && (
        <details open={required.length === 0 || setCount > 0} className="group">
          <summary className="cursor-pointer text-xs font-medium text-nexus-text-secondary select-none">
            Optional inputs ({optional.length}){setCount > 0 && ` · ${setCount} set`}
          </summary>
          <div className="grid gap-3 sm:grid-cols-2 mt-2">{optional.map(render)}</div>
        </details>
      )}
    </div>
  );
}

/** One tool input: a dropdown for fixed choices and true/false, JSON for objects, text (with {{ }}) otherwise. */
function ParamInput({ field, value, onChange, sources }: {
  field: ParamField;
  value: unknown;
  onChange: (value: unknown) => void;
  sources?: DynamicSources;
}) {
  const text = value === undefined || value === null ? '' : typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  const structured = field.type === 'object' || field.type === 'array';
  const choices = field.options ?? (field.type === 'boolean' ? ['true', 'false'] : undefined);
  const hint = field.required ? '(required)' : field.deprecated ? '(deprecated)'
    : field.defaultValue !== undefined ? `(default ${JSON.stringify(field.defaultValue)})` : undefined;
  return (
    <div className={cn('block', structured && 'sm:col-span-2')}>
      <span title={field.key}><FieldLabel hint={hint}>{field.label}</FieldLabel></span>
      {choices && !text.includes('{{') ? (
        <select value={text} aria-label={field.label} className={fieldClass}
          onChange={(e) => onChange(e.target.value === '' ? undefined : parseTyped(e.target.value, field.type))}>
          <option value="">{field.required ? 'Choose…' : 'Not set'}</option>
          {choices.map(option => <option key={option} value={option}>{option}</option>)}
        </select>
      ) : (
        <TemplateInput
          value={text}
          label={field.label}
          multiline={structured}
          mono={structured}
          placeholder={structured ? field.example : field.type === 'integer' || field.type === 'number' ? 'A number' : ''}
          sources={sources}
          onChange={(next) => onChange(parseTyped(next, field.type))}
        />
      )}
      {(field.description || (structured && !text && field.example)) && (
        <p className="text-[11px] text-nexus-text-muted mt-1">
          <span className="line-clamp-2" title={field.description}>{field.description}</span>
          {structured && !text && field.example && (
            <button type="button" className="underline" onClick={() => onChange(JSON.parse(field.example!))}>Insert example</button>
          )}
        </p>
      )}
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
  workflows: Array<{ id: number | string; name: string }>;
}

/** The settings form shown when a step card is expanded. */
export function StepConfig({ node, onConfig, tools, llmProviders, sources, workflows }: StepConfigProps) {
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
    case 'http':
      return (
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-4">
            <label className="block">
              <FieldLabel>Method</FieldLabel>
              <select value={String(c.method ?? 'GET')} onChange={(e) => onConfig({ method: e.target.value })} className={fieldClass}>
                {['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map(m => <option key={m}>{m}</option>)}
              </select>
            </label>
            <label className="block sm:col-span-3">
              <FieldLabel>URL</FieldLabel>
              <TemplateInput value={String(c.url ?? '')} onChange={(url) => onConfig({ url })} placeholder="https://api.example.com/items" sources={sources} label="URL" />
            </label>
          </div>
          <label className="block">
            <FieldLabel hint="(JSON object)">Headers</FieldLabel>
            <JsonField label="Headers" value={c.headers} onChange={(headers) => onConfig({ headers })} placeholder='{"Authorization": "Bearer ..."}' />
          </label>
          {String(c.method ?? 'GET') !== 'GET' && (
            <label className="block">
              <FieldLabel hint="(JSON or text; {{ }} allowed)">Body</FieldLabel>
              <JsonField label="Body" value={c.body} onChange={(body) => onConfig({ body })} placeholder='{"text": "{{ steps.llm_1.text }}"}' />
            </label>
          )}
          <p className="text-xs text-nexus-text-muted">Result: <code>{`{{ steps.${node.id}.status }}`}</code> and <code>{`{{ steps.${node.id}.data }}`}</code>. Error codes (4xx/5xx) fail the step.</p>
        </div>
      );
    case 'code':
      return (
        <div className="space-y-2">
          <FieldLabel hint="(JavaScript function body; read input.steps, input.trigger, input.loop and return a value)">Code</FieldLabel>
          <textarea rows={6} aria-label="Code" value={String(c.code ?? '')} onChange={(e) => onConfig({ code: e.target.value })}
            placeholder={'const items = input.steps.action_1.data.items;\nreturn items.length;'}
            className={cn(fieldClass, 'font-mono')} spellCheck={false} />
          <p className="text-xs text-nexus-text-muted">Runs in a sandbox with no network or file access, for up to 5 seconds. Result: <code>{`{{ steps.${node.id}.value }}`}</code>.</p>
        </div>
      );
    case 'workflow':
      return (
        <div className="space-y-3">
          <label className="block">
            <FieldLabel>Workflow to run</FieldLabel>
            <select value={String(c.workflow_id ?? '')} onChange={(e) => onConfig({ workflow_id: e.target.value ? Number(e.target.value) : null })} className={fieldClass}>
              <option value="">Select a workflow...</option>
              {workflows.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
          </label>
          <label className="block">
            <FieldLabel hint="(JSON object of its manual inputs)">Inputs</FieldLabel>
            <JsonField label="Inputs" value={c.inputs} onChange={(value) => onConfig({ inputs: value })} placeholder='{"who": "{{ trigger.inputs.name }}"}' />
          </label>
          <p className="text-xs text-nexus-text-muted">Its result is <code>{`{{ steps.${node.id}.result }}`}</code>.</p>
        </div>
      );
    case 'loop':
      return (
        <label className="block">
          <FieldLabel hint="(a list from an earlier step)">For each item in</FieldLabel>
          <TemplateInput value={String(c.items ?? '')} onChange={(items) => onConfig({ items })}
            placeholder="{{ steps.action_1.data.items }}" sources={sources} label="Items" />
          <span className="block text-xs text-nexus-text-muted mt-1">
            Inside the loop use <code>{'{{ loop.item }}'}</code> and <code>{'{{ loop.index }}'}</code>. Results: <code>{`{{ steps.${node.id}.results }}`}</code>.
          </span>
        </label>
      );
    case 'parallel':
      return <p className="text-xs text-nexus-text-muted">All branches start together; the next step waits for every branch. Results: <code>{`{{ steps.${node.id}.branches }}`}</code>.</p>;
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
