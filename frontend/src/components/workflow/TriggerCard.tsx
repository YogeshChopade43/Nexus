import { useEffect, useState } from 'react';
import { Plus, X } from 'lucide-react';
import { cn, getErrorMessage } from '../../lib/utils';
import { workflowService } from '../../services/workflow';
import { ActionPicker } from './ActionPicker';
import { FieldLabel, ParameterForm, fieldClass } from './StepConfig';
import type { McpServer } from '../../types/mcp';
import type { Frequency, ManualInput, ToolDefinition, TriggerTypeInfo, Weekday, WorkflowNode } from '../../types/workflow';

const TYPES = [
  { id: 'manual', label: 'Manually', icon: '👆', help: 'Run with the Run button, optionally asking for inputs' },
  { id: 'recurrence', label: 'Recurrence', icon: '🔁', help: 'Run on a schedule: every N minutes, daily, weekly, monthly' },
  { id: 'poll', label: 'When something new appears in an app', icon: '📥', help: 'Check an app regularly and run once per new item' },
  { id: 'webhook', label: 'When a webhook is called', icon: '🌐', help: 'Run when another system calls a secret URL' },
] as const;

const MORE = [
  { id: 'app_event', label: 'App event (incoming webhook)' },
  { id: 'schedule', label: 'Advanced: cron expression' },
] as const;

const WEEKDAYS: Weekday[] = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

export function defaultTriggerConfig(type: string): Record<string, unknown> {
  switch (type) {
    case 'recurrence':
      return { trigger_type: 'recurrence', frequency: 'day', interval: 1, at: '09:00', weekdays: ['mon', 'tue', 'wed', 'thu', 'fri'], month_day: 1, timezone: browserZone };
    case 'poll':
      return { trigger_type: 'poll', tool: '', parameters: {}, interval_minutes: 5, items_path: '', id_field: '' };
    case 'manual':
      return { trigger_type: 'manual', inputs: [] };
    case 'schedule':
      return { trigger_type: 'schedule', schedule: '0 9 * * 1-5', timezone: browserZone };
    default:
      return { trigger_type: type };
  }
}

export function triggerSummary(config: Record<string, unknown>): string {
  switch (config.trigger_type) {
    case 'recurrence': {
      const f = config.frequency as Frequency;
      const every = Number(config.interval ?? 1) > 1 ? `Every ${config.interval} ${f}s` : `Every ${f}`;
      if (f === 'week') return `${every} on ${(config.weekdays as string[] ?? []).join(', ')} at ${config.at}`;
      if (f === 'month') return `Monthly on day ${config.month_day} at ${config.at}`;
      if (f === 'day') return `${every} at ${config.at}`;
      return every;
    }
    case 'poll':
      return config.tool ? `Check ${config.tool} every ${config.interval_minutes ?? 5} min` : 'Choose an app operation to check';
    case 'webhook':
      return 'When the webhook URL is called';
    case 'app_event':
      return `App event: ${config.event || `any ${config.app_id ?? ''} event`}`;
    case 'schedule':
      return `Cron: ${config.schedule}`;
    default: {
      const count = (config.inputs as ManualInput[] | undefined)?.length ?? 0;
      return count ? `Manually, asking for ${count} input(s)` : 'Manually';
    }
  }
}

function RecurrenceForm({ config, onConfig }: { config: Record<string, unknown>; onConfig: (patch: Record<string, unknown>) => void }) {
  const frequency = (config.frequency as Frequency) ?? 'day';
  const [preview, setPreview] = useState<{ runs: string[]; error: string | null }>({ runs: [], error: null });
  const settings = JSON.stringify({
    frequency, interval: config.interval, at: config.at, weekdays: config.weekdays, month_day: config.month_day, timezone: config.timezone,
  });

  useEffect(() => {
    const timer = setTimeout(() => {
      workflowService.previewRecurrence(JSON.parse(settings))
        .then(r => setPreview({ runs: r.next_runs, error: null }))
        .catch(err => setPreview({ runs: [], error: getErrorMessage(err) }));
    }, 400);
    return () => clearTimeout(timer);
  }, [settings]);

  const weekdays = (config.weekdays as Weekday[]) ?? [];
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block">
          <FieldLabel>Repeat</FieldLabel>
          <select value={frequency} onChange={(e) => onConfig({ frequency: e.target.value, interval: e.target.value === 'minute' ? 15 : 1 })} className={fieldClass}>
            <option value="minute">Every N minutes</option>
            <option value="hour">Every N hours</option>
            <option value="day">Daily</option>
            <option value="week">Weekly</option>
            <option value="month">Monthly</option>
          </select>
        </label>
        {(frequency === 'minute' || frequency === 'hour' || frequency === 'day') && (
          <label className="block">
            <FieldLabel>{frequency === 'day' ? 'Every N days' : `Every N ${frequency}s`}</FieldLabel>
            <input type="number" min={frequency === 'minute' ? 5 : 1} max={1000} value={Number(config.interval ?? 1)}
              onChange={(e) => onConfig({ interval: Number(e.target.value) })} className={fieldClass} />
          </label>
        )}
        {(frequency === 'day' || frequency === 'week' || frequency === 'month') && (
          <label className="block">
            <FieldLabel>At</FieldLabel>
            <input type="time" value={String(config.at ?? '09:00')} onChange={(e) => onConfig({ at: e.target.value })} className={fieldClass} />
          </label>
        )}
        {frequency === 'month' && (
          <label className="block">
            <FieldLabel>Day of month</FieldLabel>
            <input type="number" min={1} max={31} value={Number(config.month_day ?? 1)} onChange={(e) => onConfig({ month_day: Number(e.target.value) })} className={fieldClass} />
          </label>
        )}
      </div>
      {frequency === 'week' && (
        <div>
          <FieldLabel>On</FieldLabel>
          <div className="flex flex-wrap gap-1" role="group" aria-label="Weekdays">
            {WEEKDAYS.map(day => {
              const on = weekdays.includes(day);
              return (
                <button key={day} type="button" aria-pressed={on}
                  onClick={() => onConfig({ weekdays: on ? weekdays.filter(d => d !== day) : WEEKDAYS.filter(d => d === day || weekdays.includes(d)) })}
                  className={cn('px-2.5 py-1 rounded text-xs border', on ? 'bg-nexus-accent text-nexus-bg border-nexus-accent' : 'border-nexus-border text-nexus-text-secondary')}>
                  {day[0].toUpperCase() + day.slice(1)}
                </button>
              );
            })}
          </div>
        </div>
      )}
      <label className="block sm:w-1/2">
        <FieldLabel>Timezone</FieldLabel>
        <input value={String(config.timezone ?? browserZone)} onChange={(e) => onConfig({ timezone: e.target.value })} className={fieldClass} />
      </label>
      <div className="text-xs">
        {preview.error ? (
          <p className="text-nexus-danger">{preview.error}</p>
        ) : preview.runs.length > 0 && (
          <p className="text-nexus-text-muted">Next runs: {preview.runs.map(r => new Date(r).toLocaleString()).join(' · ')}</p>
        )}
      </div>
    </div>
  );
}

function ManualInputsForm({ config, onConfig }: { config: Record<string, unknown>; onConfig: (patch: Record<string, unknown>) => void }) {
  const inputs = (config.inputs as ManualInput[]) ?? [];
  const update = (index: number, patch: Partial<ManualInput>) =>
    onConfig({ inputs: inputs.map((input, i) => (i === index ? { ...input, ...patch } : input)) });
  return (
    <div className="space-y-2">
      <FieldLabel hint="(asked each time you click Run; use as {{ trigger.inputs.<name> }})">Inputs</FieldLabel>
      {inputs.map((input, index) => (
        <div key={index} className="flex flex-wrap items-center gap-2">
          <input value={input.name} onChange={(e) => update(index, { name: e.target.value })} placeholder="name" aria-label="Input name" className={cn(fieldClass, 'w-36 font-mono')} />
          <select value={input.type} onChange={(e) => update(index, { type: e.target.value as ManualInput['type'] })} aria-label="Input type" className={cn(fieldClass, 'w-28')}>
            <option value="text">Text</option>
            <option value="number">Number</option>
            <option value="boolean">Yes / No</option>
          </select>
          <input value={input.default == null ? '' : String(input.default)} onChange={(e) => update(index, { default: e.target.value })} placeholder="default" aria-label="Default value" className={cn(fieldClass, 'w-32')} />
          <label className="flex items-center gap-1 text-xs text-nexus-text-secondary">
            <input type="checkbox" checked={input.required} onChange={(e) => update(index, { required: e.target.checked })} /> required
          </label>
          <button onClick={() => onConfig({ inputs: inputs.filter((_, i) => i !== index) })} aria-label="Remove input" className="text-nexus-text-muted hover:text-nexus-danger"><X className="w-4 h-4" /></button>
        </div>
      ))}
      {inputs.length < 20 && (
        <button onClick={() => onConfig({ inputs: [...inputs, { name: `input_${inputs.length + 1}`, type: 'text', required: false, default: '' }] })}
          className="text-xs text-nexus-accent flex items-center gap-1"><Plus className="w-3 h-3" /> Add an input</button>
      )}
    </div>
  );
}

function PollForm({ config, onConfig, servers, tools }: {
  config: Record<string, unknown>; onConfig: (patch: Record<string, unknown>) => void; servers: McpServer[]; tools: Map<string, ToolDefinition>;
}) {
  const [picking, setPicking] = useState(false);
  const tool = tools.get(String(config.tool ?? ''));
  return (
    <div className="space-y-3">
      <div>
        <FieldLabel>App operation to check</FieldLabel>
        {picking ? (
          <ActionPicker servers={servers} toolsOnly onClose={() => setPicking(false)}
            onPick={(picked) => { if (picked.type === 'action') onConfig({ tool: picked.tool, parameters: {} }); setPicking(false); }} />
        ) : (
          <button onClick={() => setPicking(true)} className={cn(fieldClass, 'text-left font-mono')}>
            {String(config.tool || 'Choose an operation that lists items (e.g. list issues)…')}
          </button>
        )}
      </div>
      <ParameterForm tool={tool} parameters={(config.parameters as Record<string, unknown>) ?? {}} onChange={(parameters) => onConfig({ parameters })} />
      <label className="block w-48">
        <FieldLabel>Check every (minutes)</FieldLabel>
        <input type="number" min={1} max={1440} value={Number(config.interval_minutes ?? 5)} onChange={(e) => onConfig({ interval_minutes: Number(e.target.value) })} className={fieldClass} />
      </label>
      <details className="text-xs">
        <summary className="cursor-pointer text-nexus-text-secondary">Advanced</summary>
        <div className="grid gap-3 sm:grid-cols-2 mt-2">
          <label className="block">
            <FieldLabel hint="(blank = first list found)">Items path</FieldLabel>
            <input value={String(config.items_path ?? '')} onChange={(e) => onConfig({ items_path: e.target.value })} placeholder="items" className={cn(fieldClass, 'font-mono')} />
          </label>
          <label className="block">
            <FieldLabel hint="(blank = id, number, key…)">ID field</FieldLabel>
            <input value={String(config.id_field ?? '')} onChange={(e) => onConfig({ id_field: e.target.value })} placeholder="id" className={cn(fieldClass, 'font-mono')} />
          </label>
        </div>
      </details>
      <p className="text-xs text-nexus-text-muted">
        The first check only records what already exists. After that, each new item starts one run, available as <code>{'{{ trigger.item }}'}</code>.
      </p>
    </div>
  );
}

interface TriggerCardProps {
  trigger: WorkflowNode;
  onChange: (trigger: WorkflowNode) => void;
  servers: McpServer[];
  tools: Map<string, ToolDefinition>;
  triggerTypes: TriggerTypeInfo[];
  webhookPath?: string;
}

export function TriggerCard({ trigger, onChange, servers, tools, triggerTypes, webhookPath }: TriggerCardProps) {
  const config = trigger.config;
  const type = String(config.trigger_type ?? 'manual');
  const onConfig = (patch: Record<string, unknown>) => onChange({ ...trigger, config: { ...config, ...patch } });
  const setType = (next: string) => onChange({ ...trigger, config: defaultTriggerConfig(next) });
  const appTypes = triggerTypes.filter(t => t.app_id);

  return (
    <div className="space-y-4">
      <div className="grid gap-2 sm:grid-cols-2">
        {TYPES.map(t => (
          <button key={t.id} onClick={() => type !== t.id && setType(t.id)} aria-pressed={type === t.id}
            className={cn('text-left p-2.5 rounded-lg border', type === t.id ? 'border-nexus-accent bg-nexus-accent-dim' : 'border-nexus-border hover:bg-nexus-bg-tertiary')}>
            <div className="text-sm text-nexus-text">{t.icon} {t.label}</div>
            <div className="text-xs text-nexus-text-muted">{t.help}</div>
          </button>
        ))}
      </div>
      <label className="flex items-center gap-2 text-xs text-nexus-text-muted">
        More:
        <select value={MORE.some(m => m.id === type) ? type : ''} onChange={(e) => e.target.value && setType(e.target.value)}
          className="px-2 py-1 rounded bg-nexus-bg-tertiary border border-nexus-border text-nexus-text">
          <option value="">—</option>
          {MORE.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
        </select>
      </label>

      {type === 'manual' && <ManualInputsForm config={config} onConfig={onConfig} />}
      {type === 'recurrence' && <RecurrenceForm config={config} onConfig={onConfig} />}
      {type === 'poll' && <PollForm config={config} onConfig={onConfig} servers={servers} tools={tools} />}
      {type === 'webhook' && (
        <p className="text-xs text-nexus-text-muted">
          {webhookPath ? 'The secret URL is shown on the workflow page.' : 'A secret URL is created when you save. The request body is available as {{ trigger.payload }}.'}
        </p>
      )}
      {type === 'app_event' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <FieldLabel>App</FieldLabel>
            <select value={String(config.app_id ?? '')} onChange={(e) => onConfig({ app_id: e.target.value, event: '' })} className={fieldClass}>
              <option value="">Select an app…</option>
              {appTypes.map(t => <option key={t.id} value={t.app_id ?? ''}>{t.label}</option>)}
            </select>
          </label>
          <label className="block">
            <FieldLabel>Event</FieldLabel>
            <select value={String(config.event ?? '')} onChange={(e) => onConfig({ event: e.target.value })} className={fieldClass} disabled={!config.app_id}>
              <option value="">Any event</option>
              {(appTypes.find(t => t.app_id === config.app_id)?.events ?? []).map(ev => <option key={ev} value={ev}>{ev}</option>)}
            </select>
          </label>
        </div>
      )}
      {type === 'schedule' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <FieldLabel hint="(min hour day month weekday)">Cron expression</FieldLabel>
            <input value={String(config.schedule ?? '')} onChange={(e) => onConfig({ schedule: e.target.value })} className={cn(fieldClass, 'font-mono')} />
          </label>
          <label className="block">
            <FieldLabel>Timezone</FieldLabel>
            <input value={String(config.timezone ?? browserZone)} onChange={(e) => onConfig({ timezone: e.target.value })} className={fieldClass} />
          </label>
        </div>
      )}
    </div>
  );
}
