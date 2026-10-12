import { useEffect, useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, FlaskConical, Plus, Save, Trash2, X } from 'lucide-react';
import { Button } from '../ui/Button';
import { Input, Textarea } from '../ui/Input';
import { cn, getErrorMessage } from '../../lib/utils';
import { mcpService } from '../../services/mcp';
import { workflowService } from '../../services/workflow';
import { graphToTree, treeToGraph, type FlowStep, type FlowTree } from './flowTree';
import { ActionPicker, BUILT_INS, type PickedAction } from './ActionPicker';
import { StepConfig, type DynamicSources } from './StepConfig';
import { toolLabel } from './toolInfo';
import { TriggerCard, defaultTriggerConfig, triggerSummary } from './TriggerCard';
import type { McpServer } from '../../types/mcp';
import type {
  NestedGraph, StepTestResult, ToolDefinition, TriggerTypeInfo, Workflow, WorkflowDraft, WorkflowEdge, WorkflowNode, WorkflowNodeType,
} from '../../types/workflow';
import type { LLMProviderConfig } from '../../types/llm';

export interface WorkflowSaveData {
  name: string;
  description: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  isActive: boolean;
}

export const NODE_ICONS: Record<WorkflowNodeType, string> = {
  trigger: '⚡', action: '⚙️', llm: '✨', condition: '🔀', transform: '🔄', delay: '⏱️', output: '📤',
  http: '🌐', code: '🧩', workflow: '🧭', loop: '🔁', parallel: '⫴',
};

/** Step types that can fail in ways worth handling ("If this step fails"). */
const HANDLES_ERRORS: WorkflowNodeType[] = ['action', 'llm', 'http', 'code', 'workflow'];
const EMPTY_GRAPH: NestedGraph = { nodes: [], edges: [] };

interface WorkflowBuilderProps {
  workflow: Workflow | null;
  /** A workflow drafted by AI to start from (only used when creating). */
  draft?: WorkflowDraft | null;
  /** Resolves to an error message, or null when saved. */
  onSave: (data: WorkflowSaveData) => Promise<string | null>;
  onCancel: () => void;
  tools: ToolDefinition[];
  llmProviders: LLMProviderConfig[];
}

function flatten(steps: FlowStep[]): WorkflowNode[] {
  return steps.flatMap(step => (step.kind === 'step' ? [step.node] : [step.node, ...flatten(step.yes), ...flatten(step.no)]));
}

function nestedGraphs(node: WorkflowNode): NestedGraph[] {
  const c = node.config;
  return [c.body, c.on_error, ...((c.branches as NestedGraph[] | undefined) ?? [])].filter(Boolean) as NestedGraph[];
}

/** Every node id in a graph, including steps inside loops, branches and error handlers. */
function collectIds(nodes: WorkflowNode[], into = new Set<string>()): Set<string> {
  for (const node of nodes) {
    into.add(node.id);
    for (const graph of nestedGraphs(node)) collectIds(graph.nodes ?? [], into);
  }
  return into;
}

function summary(node: WorkflowNode, servers: McpServer[]): string {
  const c = node.config;
  switch (node.type) {
    case 'action': {
      const name = String(c.tool ?? '');
      const [slug, ...rest] = name.split('__');
      if (!rest.length) return 'Choose a tool';
      const server = servers.find(s => s.slug === slug);
      const tool = server?.tools.find(t => t.name === name);
      return `${server?.name ?? slug} · ${tool ? toolLabel(tool) : rest.join('__')}`;
    }
    case 'llm':
      return String(c.prompt ?? '').slice(0, 70) || 'Write a prompt';
    case 'condition':
      return c.field ? `${c.field} ${c.operator ?? 'truthy'} ${c.value ?? ''}`.trim() : 'Set what to check';
    case 'transform':
    case 'output':
      return String(c.template ?? '').slice(0, 70);
    case 'delay':
      return `Wait ${c.seconds ?? 5}s`;
    case 'http':
      return `${c.method ?? 'GET'} ${c.url ?? ''}`;
    case 'code':
      return String(c.code ?? '').split('\n')[0].slice(0, 70) || 'Write some JavaScript';
    case 'loop':
      return c.items ? `For each in ${c.items}` : 'Choose a list';
    case 'parallel':
      return `${(c.branches as unknown[] | undefined)?.length ?? 0} branches`;
    case 'workflow':
      return c.workflow_id ? `Runs workflow #${c.workflow_id}` : 'Choose a workflow';
    default:
      return '';
  }
}

/** Everything a step list needs from the builder, passed down unchanged through nested lists. */
interface BuilderContext {
  tools: Map<string, ToolDefinition>;
  servers: McpServer[];
  llmProviders: LLMProviderConfig[];
  workflows: Array<{ id: number | string; name: string }>;
  workflowId: number | string | null;
  trigger: WorkflowNode | null;
  lastOutputs: Record<string, unknown>;
  expanded: string | null;
  setExpanded: (id: string | null) => void;
  pickerAt: string | null;
  setPickerAt: (key: string | null) => void;
  newNode: (picked: PickedAction) => WorkflowNode;
  tests: Record<string, StepTestResult | 'running'>;
  testStep: (node: WorkflowNode) => void;
}

function NestedSteps({ graph, onGraph, before, listKey, ctx, scopes, label, tone }: {
  graph: NestedGraph | undefined;
  onGraph: (graph: NestedGraph) => void;
  before: WorkflowNode[];
  listKey: string;
  ctx: BuilderContext;
  scopes: Array<'loop' | 'error'>;
  label: string;
  tone: string;
}) {
  const tree = graphToTree(graph?.nodes ?? [], graph?.edges ?? []);
  return (
    <div className={cn('rounded-lg p-2 space-y-2', tone)}>
      <p className="text-xs font-semibold text-nexus-text-secondary">{label}</p>
      {tree ? (
        <StepList steps={tree.steps} onChange={(steps) => onGraph(treeToGraph({ trigger: null, steps }))}
          before={before} listKey={listKey} ctx={ctx} scopes={scopes} />
      ) : (
        <p className="text-xs text-nexus-warning">These steps use a structure the builder can't display.</p>
      )}
    </div>
  );
}

function StepList({ steps, onChange, before, listKey, ctx, scopes = [] }: {
  steps: FlowStep[];
  onChange: (steps: FlowStep[]) => void;
  before: WorkflowNode[];
  listKey: string;
  ctx: BuilderContext;
  scopes?: Array<'loop' | 'error'>;
}) {
  const replace = (index: number, step: FlowStep) => onChange(steps.map((s, i) => (i === index ? step : s)));
  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= steps.length) return;
    const copy = [...steps];
    [copy[index], copy[target]] = [copy[target], copy[index]];
    onChange(copy);
  };

  const inserter = (index: number) => {
    const key = `${listKey}:${index}`;
    if (ctx.pickerAt === key) {
      return (
        <ActionPicker
          servers={ctx.servers}
          onClose={() => ctx.setPickerAt(null)}
          onPick={(picked) => {
            const node = ctx.newNode(picked);
            const step: FlowStep = node.type === 'condition' ? { kind: 'condition', node, yes: [], no: [] } : { kind: 'step', node };
            onChange([...steps.slice(0, index), step, ...steps.slice(index)]);
            ctx.setPickerAt(null);
            ctx.setExpanded(node.id);
          }}
        />
      );
    }
    return (
      <div className="flex justify-center">
        <button onClick={() => ctx.setPickerAt(key)} aria-label={index === steps.length ? 'Add a step' : 'Insert a step here'}
          className="flex items-center gap-1 px-2 py-0.5 rounded-full border border-nexus-border text-xs text-nexus-text-secondary hover:text-nexus-accent hover:border-nexus-accent bg-nexus-bg-secondary">
          <Plus className="w-3 h-3" />{index === steps.length && steps.length === 0 ? 'Add a step' : ''}
        </button>
      </div>
    );
  };

  return (
    <div className="space-y-2">
      {steps.map((step, index) => {
        const node = step.node;
        const open = ctx.expanded === node.id;
        const earlier = [...before, ...flatten(steps.slice(0, index))];
        const sources: DynamicSources = { trigger: ctx.trigger, earlierSteps: earlier, lastOutputs: ctx.lastOutputs, scopes };
        const setNode = (patch: Partial<WorkflowNode>) => replace(index, { ...step, node: { ...node, ...patch } } as FlowStep);
        const onConfig = (patch: Record<string, unknown>) => setNode({ config: { ...node.config, ...patch } });
        const test = ctx.tests[node.id];
        const branches = (node.config.branches as NestedGraph[] | undefined) ?? [];
        return (
          <div key={node.id} className="space-y-2">
            {inserter(index)}
            <div className={cn('rounded-lg border bg-nexus-bg-secondary', open ? 'border-nexus-accent' : 'border-nexus-border')}>
              <div className="flex items-center gap-2 p-2">
                <button onClick={() => ctx.setExpanded(open ? null : node.id)} aria-label={open ? 'Collapse step' : 'Expand step'} className="text-nexus-text-muted">
                  {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                </button>
                <span aria-hidden>{NODE_ICONS[node.type] ?? '⚙️'}</span>
                <div className="flex-1 min-w-0">
                  <input value={node.name} onChange={(e) => setNode({ name: e.target.value })} aria-label="Step name"
                    className="w-full bg-transparent text-sm font-medium text-nexus-text focus:outline-none" />
                  {!open && <p className="text-xs text-nexus-text-muted truncate">{summary(node, ctx.servers)}</p>}
                </div>
                <code className="hidden sm:inline text-[10px] text-nexus-text-muted">{node.id}</code>
                <button onClick={() => move(index, -1)} disabled={index === 0} aria-label="Move up" className="text-nexus-text-muted disabled:opacity-30"><ArrowUp className="w-4 h-4" /></button>
                <button onClick={() => move(index, 1)} disabled={index === steps.length - 1} aria-label="Move down" className="text-nexus-text-muted disabled:opacity-30"><ArrowDown className="w-4 h-4" /></button>
                <button onClick={() => onChange(steps.filter((_, i) => i !== index))} aria-label="Delete step" className="text-nexus-text-muted hover:text-nexus-danger"><Trash2 className="w-4 h-4" /></button>
              </div>
              {open && (
                <div className="px-3 pb-3 space-y-3 border-t border-nexus-border pt-3">
                  <StepConfig node={node} onConfig={onConfig} tools={ctx.tools} llmProviders={ctx.llmProviders} sources={sources} workflows={ctx.workflows} />
                  <div className="flex flex-wrap items-center gap-4 text-xs text-nexus-text-secondary">
                    {HANDLES_ERRORS.includes(node.type) && (
                      <>
                        <label className="flex items-center gap-2">
                          Retries
                          <input type="number" min={0} max={5} value={Number(node.config.retries ?? 0)} onChange={(e) => onConfig({ retries: Number(e.target.value) })}
                            className="w-14 px-2 py-1 rounded bg-nexus-bg-tertiary border border-nexus-border text-nexus-text" />
                        </label>
                        <label className="flex items-center gap-2">
                          <input type="checkbox" checked={Boolean(node.config.continue_on_error)} onChange={(e) => onConfig({ continue_on_error: e.target.checked })} />
                          Continue if this step fails
                        </label>
                        {!node.config.on_error && (
                          <button onClick={() => onConfig({ on_error: EMPTY_GRAPH })} className="text-nexus-accent">+ If this step fails…</button>
                        )}
                      </>
                    )}
                    {!['loop', 'parallel', 'condition'].includes(node.type) && (
                      <label className="flex items-center gap-2">
                        Timeout (s)
                        <input type="number" min={1} max={3600} placeholder="300" value={node.config.timeout_seconds ? Number(node.config.timeout_seconds) : ''}
                          onChange={(e) => onConfig({ timeout_seconds: e.target.value ? Number(e.target.value) : null })}
                          className="w-20 px-2 py-1 rounded bg-nexus-bg-tertiary border border-nexus-border text-nexus-text" />
                      </label>
                    )}
                    {!['loop', 'parallel'].includes(node.type) && (
                      <button onClick={() => ctx.testStep(node)} disabled={test === 'running'} className="flex items-center gap-1 text-nexus-accent disabled:opacity-50">
                        <FlaskConical className="w-3.5 h-3.5" /> {test === 'running' ? 'Testing…' : 'Test step'}
                      </button>
                    )}
                  </div>
                  {test && test !== 'running' && (
                    <div className={cn('rounded p-2 text-xs', test.status === 'success' ? 'bg-green-500/5' : 'bg-red-500/5')}>
                      <p className={test.status === 'success' ? 'text-green-500' : 'text-nexus-danger'}>
                        {test.status === 'success' ? `Test passed in ${test.duration_ms} ms` : `Test failed: ${test.error}`}
                      </p>
                      {test.output !== undefined && (
                        <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words font-mono text-nexus-text-secondary">{JSON.stringify(test.output, null, 2)}</pre>
                      )}
                    </div>
                  )}
                </div>
              )}

              {step.kind === 'condition' && (
                <div className="grid gap-3 md:grid-cols-2 p-3 border-t border-nexus-border">
                  {(['yes', 'no'] as const).map(branch => (
                    <div key={branch} className={cn('rounded-lg p-2 space-y-2', branch === 'yes' ? 'bg-green-500/5' : 'bg-red-500/5')}>
                      <p className={cn('text-xs font-semibold', branch === 'yes' ? 'text-green-500' : 'text-red-500')}>If {branch}</p>
                      <StepList steps={step[branch]} onChange={(branchSteps) => replace(index, { ...step, [branch]: branchSteps })}
                        before={[...earlier, node]} listKey={`${listKey}/${node.id}.${branch}`} ctx={ctx} scopes={scopes} />
                    </div>
                  ))}
                </div>
              )}

              {node.type === 'loop' && (
                <div className="p-3 border-t border-nexus-border">
                  <NestedSteps graph={node.config.body as NestedGraph | undefined} onGraph={(body) => onConfig({ body })}
                    before={[...earlier, node]} listKey={`${listKey}/${node.id}.body`} ctx={ctx} scopes={[...scopes, 'loop']}
                    label="For each item, do:" tone="bg-blue-500/5" />
                </div>
              )}

              {node.type === 'parallel' && (
                <div className="p-3 border-t border-nexus-border space-y-2">
                  <div className="grid gap-3 md:grid-cols-2">
                    {branches.map((graph, b) => (
                      <div key={b} className="relative">
                        <button onClick={() => onConfig({ branches: branches.filter((_, i) => i !== b) })} aria-label={`Remove branch ${b + 1}`}
                          className="absolute right-2 top-2 text-nexus-text-muted hover:text-nexus-danger"><X className="w-3.5 h-3.5" /></button>
                        <NestedSteps graph={graph} onGraph={(g) => onConfig({ branches: branches.map((x, i) => (i === b ? g : x)) })}
                          before={[...earlier]} listKey={`${listKey}/${node.id}.branch${b}`} ctx={ctx} scopes={scopes}
                          label={`Branch ${b + 1}`} tone="bg-purple-500/5" />
                      </div>
                    ))}
                  </div>
                  <button onClick={() => onConfig({ branches: [...branches, EMPTY_GRAPH] })} className="text-xs text-nexus-accent">+ Add branch</button>
                </div>
              )}

              {node.config.on_error != null && HANDLES_ERRORS.includes(node.type) && (
                <div className="p-3 border-t border-nexus-border relative">
                  <button onClick={() => onConfig({ on_error: null })} aria-label="Remove error handler"
                    className="absolute right-4 top-4 text-nexus-text-muted hover:text-nexus-danger"><X className="w-3.5 h-3.5" /></button>
                  <NestedSteps graph={node.config.on_error as NestedGraph} onGraph={(on_error) => onConfig({ on_error })}
                    before={[...earlier]} listKey={`${listKey}/${node.id}.on_error`} ctx={ctx} scopes={[...scopes, 'error']}
                    label="If this step fails, do: (then continue)" tone="bg-red-500/5" />
                </div>
              )}
            </div>
          </div>
        );
      })}
      {inserter(steps.length)}
    </div>
  );
}

export function WorkflowBuilder({ workflow, draft, onSave, onCancel, tools, llmProviders }: WorkflowBuilderProps) {
  const [name, setName] = useState(workflow?.name ?? draft?.name ?? '');
  const [description, setDescription] = useState(workflow?.description ?? draft?.description ?? '');
  const [isActive, setIsActive] = useState(workflow?.isActive ?? true);
  const initialTree = useMemo<FlowTree | null>(() => {
    if (workflow) return graphToTree(workflow.nodes, workflow.edges);
    if (draft) return graphToTree(draft.nodes, draft.edges);
    return { trigger: { id: 'trigger_1', type: 'trigger', name: 'Trigger', config: defaultTriggerConfig('manual') }, steps: [] };
  }, [workflow, draft]);
  const [tree, setTree] = useState<FlowTree | null>(initialTree);
  const [expanded, setExpanded] = useState<string | null>(workflow ? null : 'trigger_1');
  const [pickerAt, setPickerAt] = useState<string | null>(null);
  const [servers, setServers] = useState<McpServer[]>([]);
  const [triggerTypes, setTriggerTypes] = useState<TriggerTypeInfo[]>([]);
  const [workflows, setWorkflows] = useState<Array<{ id: number | string; name: string }>>([]);
  const [lastOutputs, setLastOutputs] = useState<Record<string, unknown>>({});
  const [tests, setTests] = useState<Record<string, StepTestResult | 'running'>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    // Picker contents; failures just leave the lists empty.
    mcpService.list().then(setServers).catch(() => {});
    workflowService.getTriggerTypes().then(setTriggerTypes).catch(() => {});
    workflowService.getWorkflows()
      .then(list => setWorkflows(list.filter(w => w.id !== workflow?.id).map(w => ({ id: w.id, name: w.name }))))
      .catch(() => {});
  }, [workflow?.id]);

  useEffect(() => {
    // Outputs of the latest run make dynamic content and "Test step" more specific.
    if (!workflow) return;
    workflowService.getWorkflowRuns(workflow.id).then(({ runs }) => {
      const run = runs[0];
      if (!run) return;
      const outputs: Record<string, unknown> = { __trigger: (run.input_data as Record<string, unknown> | undefined)?.trigger };
      for (const event of run.trace ?? run.events ?? []) {
        if (event.nodeId && event.output && !event.parent) outputs[event.nodeId] = event.output;
      }
      setLastOutputs(outputs);
    }).catch(() => {});
  }, [workflow]);

  const toolMap = useMemo(() => new Map(tools.map(t => [t.tool_name, t])), [tools]);

  const newNode = (picked: PickedAction): WorkflowNode => {
    const ids = tree ? collectIds(treeToGraph(tree).nodes) : new Set<string>();
    let n = 1;
    while (ids.has(`${picked.type}_${n}`)) n++;
    const id = `${picked.type}_${n}`;
    const defaults: Record<string, Record<string, unknown>> = {
      action: picked.type === 'action' ? { tool: picked.tool, parameters: {} } : {},
      condition: { operator: 'not_empty' },
      delay: { seconds: 5 },
      http: { method: 'GET', url: '' },
      code: { code: 'return input.steps;' },
      loop: { items: '', body: EMPTY_GRAPH },
      parallel: { branches: [EMPTY_GRAPH, EMPTY_GRAPH] },
      workflow: { workflow_id: null, inputs: {} },
    };
    const label = picked.type === 'action' ? picked.name : BUILT_INS.find(b => b.type === picked.type)?.name ?? picked.name;
    return { id, type: picked.type, name: label, config: { ...(defaults[picked.type] ?? {}) } };
  };

  const testStep = (node: WorkflowNode) => {
    setTests(prev => ({ ...prev, [node.id]: 'running' }));
    const { __trigger, ...steps } = lastOutputs;
    workflowService.testStep({ node, workflow_id: workflow?.id, sample: { steps, trigger: __trigger ?? {} } })
      .then(result => setTests(prev => ({ ...prev, [node.id]: result })))
      .catch(err => setTests(prev => ({ ...prev, [node.id]: { status: 'failed', error: getErrorMessage(err), duration_ms: 0 } })));
  };

  const handleSave = async () => {
    if (!tree) return;
    if (!name.trim()) {
      setSaveError('Give the workflow a name');
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const { nodes, edges } = treeToGraph(tree);
      const error = await onSave({ name: name.trim(), description, nodes, edges, isActive });
      if (error) setSaveError(error);
    } finally {
      setSaving(false);
    }
  };

  const ctx: BuilderContext = {
    tools: toolMap, servers, llmProviders, workflows, workflowId: workflow?.id ?? null, trigger: tree?.trigger ?? null, lastOutputs,
    expanded, setExpanded, pickerAt, setPickerAt, newNode, tests, testStep,
  };

  return (
    <div className="flex flex-col max-h-[78vh]">
      <div className="space-y-4 overflow-y-auto pr-1 flex-1">
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Daily issue digest" required />
          <label className="flex items-center gap-2 cursor-pointer self-end pb-2">
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} className="w-4 h-4" />
            <span className="text-sm text-nexus-text">
              {tree?.trigger && tree.trigger.config.trigger_type !== 'manual'
                ? 'Active (runs on its own while on)' : 'Enabled (can be run)'}
            </span>
          </label>
        </div>
        <Textarea label="Description" value={description} onChange={(e) => setDescription(e.target.value)} rows={2} placeholder="What this workflow does" />
        {draft?.warnings && draft.warnings.length > 0 && (
          <ul className="text-xs text-nexus-warning space-y-0.5">{draft.warnings.map(w => <li key={w}>⚠ {w}</li>)}</ul>
        )}

        {tree === null ? (
          <div role="alert" className="p-4 rounded-lg border border-nexus-warning/40 text-sm text-nexus-text-secondary">
            This workflow was created with a structure the step builder can&apos;t display. You can still run or delete it,
            but editing its steps here is disabled so nothing gets lost.
          </div>
        ) : (
          <div className="max-w-3xl mx-auto w-full space-y-2">
            {tree.trigger ? (
              <div className={cn('rounded-lg border bg-nexus-bg-secondary', expanded === tree.trigger.id ? 'border-nexus-accent' : 'border-nexus-border')}>
                <button className="w-full flex items-center gap-2 p-2 text-left" onClick={() => setExpanded(expanded === tree.trigger!.id ? null : tree.trigger!.id)}>
                  {expanded === tree.trigger.id ? <ChevronDown className="w-4 h-4 text-nexus-text-muted" /> : <ChevronRight className="w-4 h-4 text-nexus-text-muted" />}
                  <span aria-hidden>⚡</span>
                  <span className="flex-1 min-w-0">
                    <span className="block text-sm font-medium text-nexus-text">Trigger</span>
                    <span className="block text-xs text-nexus-text-muted truncate">{triggerSummary(tree.trigger.config)}</span>
                  </span>
                </button>
                {expanded === tree.trigger.id && (
                  <div className="px-3 pb-3 pt-3 border-t border-nexus-border">
                    <TriggerCard trigger={tree.trigger} onChange={(trigger) => setTree({ ...tree, trigger })} servers={servers}
                      tools={toolMap} triggerTypes={triggerTypes} webhookPath={workflow?.trigger_config?.webhook_path} />
                  </div>
                )}
              </div>
            ) : (
              <button onClick={() => setTree({ ...tree, trigger: { id: 'trigger_1', type: 'trigger', name: 'Trigger', config: defaultTriggerConfig('manual') } })}
                className="w-full p-3 rounded-lg border border-dashed border-nexus-border text-sm text-nexus-accent">⚡ Add a trigger</button>
            )}
            <StepList steps={tree.steps} onChange={(steps) => setTree({ ...tree, steps })} before={[]} listKey="root" ctx={ctx} />
          </div>
        )}
      </div>

      {saveError && <p className="mt-3 text-sm text-nexus-danger" role="alert">{saveError}</p>}
      <div className="flex justify-end gap-2 pt-4 mt-2 border-t border-nexus-border">
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={saving}>Cancel</Button>
        <Button variant="primary" size="sm" onClick={handleSave} loading={saving} disabled={saving || tree === null} className="gap-1.5">
          <Save className="w-4 h-4" /> Save
        </Button>
      </div>
    </div>
  );
}
