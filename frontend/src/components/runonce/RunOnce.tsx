import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle, CalendarClock, Check, CheckCircle2, Gift, Moon, Pause, Pencil, Play, Plus, Repeat1, ShieldCheck, Trash2, X,
} from 'lucide-react';
import { listApps } from '../../services/integrations';
import { workflowService } from '../../services/workflow';
import { useLLM } from '../../hooks/useLLM';
import { ActionPicker, type PickedAction } from '../workflow/ActionPicker';
import { StepConfig } from '../workflow/StepConfig';
import { NodeTile } from '../workflow/NodeTile';
import { nodeFor } from '../workflow/WorkflowBuilder';
import type { McpServer } from '../../types/mcp';
import type { ToolDefinition, WorkflowNode } from '../../types/workflow';
import { api } from '../../services/api';
import { Card } from '../ui/Card';
import { PageHeader } from '../ui/PageHeader';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { Modal } from '../ui/Modal';
import { fieldClass } from '../ui/Input';
import { cn, formatRelativeTime, getErrorMessage } from '../../lib/utils';

type Kind = 'at' | 'quiet';
type Status = 'scheduled' | 'armed' | 'warning' | 'off' | 'done' | 'missed';

interface Item {
  id: number;
  workflowId: number;
  name: string;
  kind: Kind;
  at: string | null;
  days: number | null;
  enabled: boolean;
  status: Status;
  /** Steps in its workflow (besides the trigger); 0 = nothing to do yet. */
  steps?: number;
  runsAt: string | null;
  quietSince: string | null;
  warnedAt: string | null;
  ranAt: string | null;
  missedAt: string | null;
}

interface Overview {
  items: Item[];
  lastCheckIn: string | null;
  channels: string[];
}

interface Draft { name: string; kind: Kind; at?: string; days?: number; nodes?: WorkflowNode[] }

const runOnceService = {
  list: () => api.get<Overview>('/api/run-once'),
  create: (draft: Draft) => api.post<Item>('/api/run-once', draft),
  change: (id: number, changes: Partial<Draft> & { enabled?: boolean }) => api.patch<Item>(`/api/run-once/${id}`, changes),
  remove: (id: number) => api.delete<void>(`/api/run-once/${id}`),
  checkIn: () => api.post<Overview>('/api/run-once/check-in'),
};

const DAY_MS = 86_400_000;
const PRESETS = [7, 14, 30, 60];
const date = (iso: string) => new Date(iso).toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit' });

/** "in 3 days", "in 5 hours". */
function until(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return 'any moment now';
  const days = Math.round(ms / DAY_MS);  // 29.9 days reads as 30
  if (days >= 1) return `in ${days} day${days === 1 ? '' : 's'}`;
  const hours = Math.max(1, Math.round(ms / 3_600_000));
  return `in ${hours} hour${hours === 1 ? '' : 's'}`;
}

/** A datetime-local value (this computer's time) for an ISO moment, and back. */
const toLocalInput = (iso: string) => {
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
};

const STATUS: Record<Status, { label: string; badge: 'default' | 'success' | 'warning' | 'accent' | 'danger' }> = {
  scheduled: { label: 'Scheduled', badge: 'accent' },
  armed: { label: 'On', badge: 'success' },
  warning: { label: 'Warning', badge: 'warning' },
  off: { label: 'Paused', badge: 'default' },
  done: { label: 'Ran', badge: 'default' },
  missed: { label: 'Missed', badge: 'danger' },
};

const EXAMPLES: { title: string; body: string; icon: typeof Gift; draft: Draft }[] = [
  { title: 'A birthday message on the day', body: 'Email or message someone on a date you pick.', icon: Gift,
    draft: { name: 'Birthday message', kind: 'at' } },
  { title: 'Share important info if I go quiet', body: 'If Nexus doesn’t hear from you, tell your family where things are.', icon: ShieldCheck,
    draft: { name: 'Share important info with family', kind: 'quiet', days: 14 } },
];

const TRIGGER: WorkflowNode = { id: 'trigger', type: 'trigger', name: 'When it’s time', config: { trigger_type: 'manual' } };
const CANVAS_ONLY: WorkflowNode['type'][] = ['condition', 'loop', 'parallel'];

/** What it does, one step after another: pick an action (any connected app, or a built-in step), fill it in. */
function StepsEditor({ steps, onChange }: { steps: WorkflowNode[]; onChange: (steps: WorkflowNode[]) => void }) {
  const [picking, setPicking] = useState(false);
  const [servers, setServers] = useState<McpServer[]>([]);
  const [tools, setTools] = useState<Map<string, ToolDefinition>>(new Map());
  const [workflows, setWorkflows] = useState<Array<{ id: number | string; name: string }>>([]);
  const { configs: llmProviders } = useLLM();

  useEffect(() => {  // what the picker and the step forms offer; failures just leave them empty
    listApps().then(setServers).catch(() => {});
    workflowService.getTools().then(list => setTools(new Map(list.map(t => [t.tool_name, t])))).catch(() => {});
    workflowService.getWorkflows().then(list => setWorkflows(list.map(w => ({ id: w.id, name: w.name })))).catch(() => {});
  }, []);

  const add = (picked: PickedAction) => {
    onChange([...steps, nodeFor(picked, new Set(steps.map(n => n.id)))]);
    setPicking(false);
  };
  const change = (index: number, patch: Record<string, unknown>) =>
    onChange(steps.map((node, i) => (i === index ? { ...node, config: { ...node.config, ...patch } } : node)));

  return (
    <div className="space-y-2">
      {steps.map((node, i) => (
        <div key={node.id} className="rounded-lg border border-nexus-border bg-nexus-bg">
          <div className="flex items-center gap-2 border-b border-nexus-border px-3 py-2">
            <span className="w-4 text-right text-[11px] tabular-nums text-nexus-text-muted">{i + 1}</span>
            <NodeTile type={node.type} size="sm" />
            <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-nexus-text">{node.name}</span>
            <button type="button" aria-label={`Remove step ${i + 1}`} onClick={() => onChange(steps.filter((_, j) => j !== i))}
              className="rounded p-1 text-nexus-text-muted hover:bg-nexus-bg-tertiary hover:text-nexus-danger">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="space-y-3 p-3">
            <StepConfig node={node} onConfig={(patch) => change(i, patch)} tools={tools} llmProviders={llmProviders} workflows={workflows}
              sources={{ trigger: TRIGGER, earlierSteps: steps.slice(0, i), lastOutputs: {} }} />
          </div>
        </div>
      ))}
      {picking ? (
        <ActionPicker servers={servers} without={CANVAS_ONLY} onPick={add} onClose={() => setPicking(false)} />
      ) : (
        <button type="button" onClick={() => setPicking(true)}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-dashed border-nexus-border px-3 py-2.5 text-[13px] font-medium text-nexus-text-secondary transition-colors hover:border-nexus-accent/50 hover:text-nexus-accent-text">
          <Plus className="h-3.5 w-3.5" /> {steps.length ? 'Add another step' : 'Add a step'}
        </button>
      )}
      {steps.length === 0 && !picking && (
        <p className="text-xs text-nexus-text-muted">For example: send a Telegram message, send an email, or ask the AI to write something first.</p>
      )}
    </div>
  );
}

/** Make one, or change when an existing one runs. */
function RunOnceDialog({ initial, item, onSave, onClose }: {
  initial: Draft; item?: Item; onSave: (draft: Draft) => Promise<void>; onClose: () => void;
}) {
  const [name, setName] = useState(initial.name);
  const [kind, setKind] = useState<Kind>(initial.kind);
  const [at, setAt] = useState(initial.at ? toLocalInput(initial.at) : '');
  const [days, setDays] = useState(String(initial.days ?? 14));
  const [steps, setSteps] = useState<WorkflowNode[]>(initial.nodes ?? []);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const wanted = Number(days);
  const valid = name.trim() && (kind === 'at' ? !!at : Number.isInteger(wanted) && wanted >= 3 && wanted <= 365)
    && (item || steps.length > 0);  // a new one needs something to do

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const when = kind === 'at' ? { at: new Date(at).toISOString() } : { days: wanted };
      await onSave({ name: name.trim(), kind, ...when, ...(item ? {} : { nodes: steps }) });
      onClose();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const choice = (value: Kind, title: string, body: string, Icon: typeof Moon) => (
    <label className={cn('flex cursor-pointer gap-3 rounded-lg border p-3 transition-colors',
      kind === value ? 'border-nexus-accent/60 bg-nexus-accent/5' : 'border-nexus-border hover:bg-nexus-bg-tertiary/50',
      item && 'cursor-not-allowed opacity-60')}>
      <input type="radio" name="kind" value={value} checked={kind === value} disabled={!!item}
        onChange={() => setKind(value)} className="sr-only" aria-label={title} />
      <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', kind === value ? 'text-nexus-accent-text' : 'text-nexus-text-muted')} aria-hidden />
      <span>
        <span className="block text-[13px] font-medium text-nexus-text">{title}</span>
        <span className="block text-xs text-nexus-text-secondary">{body}</span>
      </span>
    </label>
  );

  return (
    <Modal open onClose={onClose} title={item ? `Change “${item.name}”` : 'New run-once'} size={item ? 'md' : 'lg'}>
      <form onSubmit={(e) => void save(e)} className="space-y-4">
        <label className="block space-y-1">
          <span className="block text-[13px] font-medium text-nexus-text">Name</span>
          <input aria-label="Name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} className={fieldClass}
            placeholder="e.g. Birthday message to Mom" />
        </label>
        <fieldset className="space-y-2">
          <legend className="mb-1 text-[13px] font-medium text-nexus-text">When it runs</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {choice('at', 'On a date', 'At a date and time you pick.', CalendarClock)}
            {choice('quiet', 'If I go quiet', 'If Nexus doesn’t hear from you for a while. Warns you first.', Moon)}
          </div>
        </fieldset>
        {kind === 'at' ? (
          <label className="block space-y-1">
            <span className="block text-[13px] font-medium text-nexus-text">Date and time</span>
            <input type="datetime-local" aria-label="Date and time" value={at} min={toLocalInput(new Date().toISOString())}
              onChange={(e) => setAt(e.target.value)} className={cn(fieldClass, 'w-auto')} />
          </label>
        ) : (
          <div className="space-y-2">
            <span className="block text-[13px] font-medium text-nexus-text">Quiet for</span>
            <div className="flex flex-wrap items-center gap-1.5">
              {PRESETS.map(preset => (
                <button key={preset} type="button" onClick={() => setDays(String(preset))} aria-pressed={wanted === preset}
                  className={cn('h-8 rounded-md border px-2.5 text-xs font-medium transition-colors',
                    wanted === preset ? 'border-nexus-accent/50 bg-nexus-accent/10 text-nexus-accent-text'
                      : 'border-nexus-border text-nexus-text-secondary hover:bg-nexus-bg-tertiary')}>
                  {preset} days
                </button>
              ))}
              <input type="number" min={3} max={365} value={days} onChange={(e) => setDays(e.target.value)}
                aria-label="Days without hearing from you" className={cn(fieldClass, 'h-8 w-20')} />
            </div>
            <p className="text-xs text-nexus-text-muted">Nexus warns you every day from 3 days before, and never runs it sooner than 48 hours after the first warning.</p>
          </div>
        )}
        {!item && (
          <fieldset className="space-y-2">
            <legend className="mb-1 text-[13px] font-medium text-nexus-text">What happens</legend>
            <StepsEditor steps={steps} onChange={setSteps} />
          </fieldset>
        )}
        {error && <p role="alert" className="text-xs text-nexus-danger">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button type="submit" size="sm" loading={busy} disabled={!valid}>{item ? 'Save' : 'Create'}</Button>
        </div>
        {item && <p className="text-xs text-nexus-text-muted">To change what it does, use Edit steps on its card.</p>}
      </form>
    </Modal>
  );
}

function ItemCard({ item, onPause, onResume, onChange, onDelete }: {
  item: Item; onPause: () => void; onResume: () => void; onChange: () => void; onDelete: () => void;
}) {
  const quiet = item.kind === 'quiet';
  const live = item.status === 'scheduled' || item.status === 'armed' || item.status === 'warning';
  const quietDays = item.quietSince ? Math.max(0, (Date.now() - new Date(item.quietSince).getTime()) / DAY_MS) : 0;
  const share = quiet && item.days ? Math.min(1, quietDays / item.days) : 0;
  const Icon = quiet ? Moon : CalendarClock;
  return (
    <Card className={cn('flex flex-col gap-3', item.status === 'warning' && 'border-nexus-warning/40 bg-nexus-warning/5')}>
      <div className="flex items-start gap-3">
        <span className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-lg',
          live ? 'bg-nexus-accent/10 text-nexus-accent-text' : 'bg-nexus-bg-tertiary text-nexus-text-muted')}>
          <Icon className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h3 className="break-words text-[13px] font-semibold text-nexus-text">{item.name}</h3>
            <Badge size="sm" variant={STATUS[item.status].badge}>{STATUS[item.status].label}</Badge>
          </div>
          <p className="mt-0.5 text-xs text-nexus-text-secondary">
            {quiet ? `If you go quiet for ${item.days} days` : item.at ? `On ${date(item.at)}` : ''}
            {item.status === 'scheduled' && item.runsAt && <span className="text-nexus-text-muted"> · {until(item.runsAt)}</span>}
          </p>
        </div>
      </div>

      {quiet && (item.status === 'armed' || item.status === 'warning') && (
        <div className="space-y-1">
          <div role="progressbar" aria-valuenow={Math.round(share * 100)} aria-valuemin={0} aria-valuemax={100}
            aria-label={`${Math.floor(quietDays)} of ${item.days} quiet days`} className="h-1.5 overflow-hidden rounded-full bg-nexus-bg-tertiary">
            <div className={cn('h-full rounded-full transition-[width] duration-500', item.status === 'warning' ? 'bg-nexus-warning' : 'bg-nexus-accent')}
              style={{ width: `${Math.max(share * 100, 1.5)}%` }} />
          </div>
          <p className="text-[11px] text-nexus-text-muted">
            {Math.floor(quietDays)} of {item.days} quiet days{item.runsAt ? ` · runs ${date(item.runsAt)} at the earliest` : ''}
          </p>
        </div>
      )}
      {item.steps === 0 && item.status !== 'done' && (
        <p className="flex items-start gap-1.5 text-xs text-nexus-warning">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          No steps yet: use Edit steps to add what it should do, like a Telegram message or an email.
        </p>
      )}
      {item.status === 'warning' && (
        <p className="flex items-start gap-1.5 text-xs text-nexus-text">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-nexus-warning" aria-hidden />
          Nexus hasn’t heard from you. Check in to stop it.
        </p>
      )}
      {item.status === 'done' && item.ranAt && <p className="text-xs text-nexus-text-secondary">Ran {formatRelativeTime(item.ranAt)} ({date(item.ranAt)}).</p>}
      {item.status === 'missed' && item.missedAt && (
        <p className="text-xs text-nexus-danger">Missed: Nexus was off when it was due. Pick a new time to run it.</p>
      )}

      <div className="mt-auto flex flex-wrap items-center gap-1 border-t border-nexus-border pt-3">
        <Link to={`/workflows?open=${item.workflowId}`}
          className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium text-nexus-accent-text hover:bg-nexus-bg-tertiary hover:no-underline">
          Edit steps →
        </Link>
        <span className="flex-1" />
        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={onChange}>
          <Pencil className="h-3.5 w-3.5" /> {item.status === 'done' || item.status === 'missed' ? 'Run again…' : 'Change'}
        </Button>
        {live && (
          <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" aria-label={`Pause ${item.name}`} onClick={onPause}>
            <Pause className="h-3.5 w-3.5" /> Pause
          </Button>
        )}
        {item.status === 'off' && (
          <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" aria-label={`Resume ${item.name}`} onClick={onResume}>
            <Play className="h-3.5 w-3.5" /> Resume
          </Button>
        )}
        <Button variant="ghost" size="sm" className="h-7 w-7 px-0 text-nexus-text-muted hover:text-nexus-danger"
          aria-label={`Delete ${item.name}`} onClick={onDelete}>
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </Card>
  );
}

/** The Run once page: workflows that run a single time, on a date or if you go quiet. */
export function RunOnce() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dialog, setDialog] = useState<{ initial: Draft; item?: Item } | null>(null);

  const load = useCallback(() => {
    runOnceService.list().then(setOverview, err => setError(getErrorMessage(err)));
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 8000);
    return () => clearTimeout(timer);
  }, [notice]);

  const run = (work: Promise<unknown>) => work.then(load, err => setError(getErrorMessage(err)));
  const items = overview?.items ?? [];
  const watching = items.filter(i => i.kind === 'quiet' && (i.status === 'armed' || i.status === 'warning'));

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader title="Run once" description="Workflows that run a single time, on a date or if you go quiet, and then stop."
        actions={<Button size="sm" onClick={() => setDialog({ initial: { name: '', kind: 'at' } })}><Plus className="h-3.5 w-3.5" /> New run-once</Button>} />

      {error && <p role="alert" className="text-[13px] text-nexus-danger">{error}</p>}

      {watching.length > 0 && overview && (
        <Card className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <Moon className="hidden h-5 w-5 shrink-0 text-nexus-accent-text sm:block" aria-hidden />
          <div className="min-w-0 flex-1 text-[13px]">
            <p className="font-medium text-nexus-text">
              {watching.length === 1 ? '1 run-once is' : `${watching.length} run-onces are`} waiting in case you go quiet
            </p>
            <p className="text-xs text-nexus-text-secondary">
              {overview.lastCheckIn ? `Last check-in ${formatRelativeTime(overview.lastCheckIn)}.` : 'Counting from when you set it up.'} Chatting with Nexus,
              here or with its bot, counts. Warnings go to the bell{overview.channels.length ? ` and ${overview.channels.join(', ')}` : ''}.
              {!overview.channels.length && <> <Link to="/servers?connect=telegram" className="text-nexus-accent-text">Link Telegram</Link> to get them on your phone.</>}
            </p>
            {notice && (
              <p role="status" className="mt-1 flex items-center gap-1.5 text-xs text-nexus-success">
                <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden /> {notice}
              </p>
            )}
          </div>
          <Button onClick={() => {
            runOnceService.checkIn().then(next => { setOverview(next); setNotice('Checked in. Every “if I go quiet” count starts over.'); },
              err => setError(getErrorMessage(err)));
          }}>
            <Check className="h-4 w-4" /> I&apos;m here
          </Button>
        </Card>
      )}

      {!overview ? <Card><p className="text-[13px] text-nexus-text-muted">Loading…</p></Card>
        : items.length === 0 ? (
          <Card className="space-y-4 py-8 text-center">
            <Repeat1 className="mx-auto h-8 w-8 text-nexus-text-muted" aria-hidden />
            <div>
              <h2 className="text-[15px] font-semibold text-nexus-text">Nothing set to run once yet</h2>
              <p className="mx-auto mt-1 max-w-md text-[13px] text-nexus-text-secondary">
                For things that should happen exactly once: on a date you pick, or only if Nexus stops hearing from you.
              </p>
            </div>
            <div className="mx-auto grid max-w-2xl gap-3 text-left sm:grid-cols-2">
              {EXAMPLES.map(example => (
                <button key={example.title} type="button" onClick={() => setDialog({ initial: example.draft })}
                  className="flex gap-3 rounded-lg border border-nexus-border p-3 text-left transition-colors hover:border-nexus-border-hover hover:bg-nexus-bg-tertiary/50">
                  <example.icon className="mt-0.5 h-4 w-4 shrink-0 text-nexus-accent-text" aria-hidden />
                  <span>
                    <span className="block text-[13px] font-medium text-nexus-text">{example.title}</span>
                    <span className="block text-xs text-nexus-text-secondary">{example.body}</span>
                  </span>
                </button>
              ))}
            </div>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {items.map(item => (
              <ItemCard key={item.id} item={item}
                onPause={() => void run(runOnceService.change(item.id, { enabled: false }))}
                onResume={() => void run(runOnceService.change(item.id, { enabled: true }))}
                onChange={() => setDialog({ item, initial: { name: item.name, kind: item.kind, at: item.at ?? undefined, days: item.days ?? undefined } })}
                onDelete={() => {
                  if (window.confirm(`Delete “${item.name}” and its steps?`)) void run(runOnceService.remove(item.id));
                }} />
            ))}
          </div>
        )}

      <details className="rounded-xl border border-nexus-border bg-nexus-bg-secondary p-4 text-[13px] text-nexus-text-secondary">
        <summary className="cursor-pointer font-medium text-nexus-text">How run once works</summary>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 text-xs">
          <li><b className="text-nexus-text">On a date:</b> runs at that minute. If Nexus was off then, it still runs up to 12 hours late; after that it&apos;s marked missed and you&apos;re told, instead of running days late.</li>
          <li><b className="text-nexus-text">If I go quiet:</b> using Nexus checks you in. Nexus warns you every day from 3 days before, and never runs it sooner than 48 hours after the first warning, even after weeks with this computer off.</li>
          <li>Each runs once, then stops. &ldquo;Run again…&rdquo; sets a new time. Running one by hand asks you to confirm first.</li>
          <li>Only runs while Nexus is running. Steps are stored on this computer: point people to where things are rather than pasting passwords.</li>
        </ul>
      </details>

      {dialog && (
        <RunOnceDialog initial={dialog.initial} item={dialog.item} onClose={() => setDialog(null)}
          onSave={async (draft) => {
            if (dialog.item) {
              await runOnceService.change(dialog.item.id, {
                name: draft.name, ...(draft.kind === 'at' ? { at: draft.at } : { days: draft.days }), enabled: true,
              });
            } else {
              await runOnceService.create(draft);
            }
            load();
          }} />
      )}
    </div>
  );
}

/** Across the top of every page while a run-once is about to run because you've gone quiet. */
export function RunOnceBanner() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const load = useCallback(() => { runOnceService.list().then(setOverview, () => {}); }, []);
  useEffect(() => {
    load();
    const timer = setInterval(load, 5 * 60_000);
    return () => clearInterval(timer);
  }, [load]);

  const warning = overview?.items.find(i => i.status === 'warning');
  if (!warning) return null;
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 border-b border-nexus-warning/30 bg-nexus-warning/10 px-4 py-2.5 text-[13px] text-nexus-text">
      <AlertTriangle className="h-4 w-4 shrink-0 text-nexus-warning" aria-hidden />
      <span className="flex-1">
        “{warning.name}” runs {warning.runsAt ? `on ${date(warning.runsAt)}` : 'soon'} because Nexus hasn&apos;t heard from you.
      </span>
      <Button size="sm" onClick={() => { runOnceService.checkIn().then(setOverview, () => {}); }}>I&apos;m here</Button>
    </div>
  );
}
