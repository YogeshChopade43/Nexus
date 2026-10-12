import { runState } from './runState';
import { useState, useCallback, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AlertCircle, Copy, Download, Edit3, History, LayoutTemplate, Play, Plus, RotateCcw, Sparkles, Square, Upload, Zap } from 'lucide-react';
import { cn, formatRelativeTime, getErrorMessage } from '../../lib/utils';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';
import { WorkflowList } from './WorkflowList';
import { NODE_ICONS, WorkflowBuilder, type WorkflowSaveData } from './WorkflowBuilder';
import { RunInputsModal } from './RunInputsModal';
import { WorkflowCanvas } from './WorkflowCanvas';
import { triggerSummary } from './TriggerCard';
import { ExecutionTrace } from './ExecutionTrace';
import { useWorkflows } from '../../hooks/useWorkflows';
import { useLLM } from '../../hooks/useLLM';
import { workflowService } from '../../services/workflow';
import { api } from '../../services/api';
import type {
  ExecutionTraceEntry, ManualInput, ToolDefinition, Workflow, WorkflowDraft, WorkflowExecution, WorkflowId, WorkflowTemplate, WorkflowVersion,
} from '../../types/workflow';

const STATUS_CLASSES: Record<string, string> = {
  completed: 'bg-green-500/15 text-green-400',
  running: 'bg-blue-500/15 text-blue-400',
  failed: 'bg-red-500/15 text-red-400',
  partial: 'bg-amber-500/15 text-amber-400',
  skipped: 'bg-gray-500/15 text-gray-400',
  cancelled: 'bg-gray-500/15 text-gray-400',
};

const POLL_MS = 800;
const TONE_STYLES = { success: 'bg-green-500/15 text-green-500', danger: 'bg-red-500/15 text-red-500', default: 'bg-gray-500/15 text-gray-400' };

function describeTrigger(workflow: Workflow): string {
  const t = workflow.trigger_config;
  const next = t?.next_run_at ? ` · next ${new Date(t.next_run_at).toLocaleString()}` : workflow.isActive ? '' : ' · stopped';
  switch (t?.type) {
    case 'recurrence':
    case 'poll':
      return `${triggerSummary({ ...t, trigger_type: t.type })}${next}`;
    case 'schedule':
      return `Schedule: ${t.schedule} (${t.timezone || 'UTC'})${t.next_run_at ? ` · next ${new Date(t.next_run_at).toLocaleString()}` : workflow.isActive ? '' : ' · stopped'}`;
    case 'webhook':
      return 'Webhook';
    case 'app_event':
      return `App event: ${t.event || `any ${t.app_id} event`}`;
    default:
      return triggerSummary({ ...(t ?? {}), trigger_type: 'manual' });
  }
}

function manualInputs(workflow: Workflow): ManualInput[] {
  const t = workflow.trigger_config;
  return t?.type === 'manual' ? t.inputs ?? [] : [];
}

export function WorkflowPage() {
  const {
    workflows, currentWorkflow, runs, loading, runsLoading, error,
    createWorkflow, updateWorkflow, deleteWorkflow, selectWorkflow, fetchWorkflowRuns, fetchWorkflows,
  } = useWorkflows();
  const { configs: llmProviders } = useLLM();

  const [tools, setTools] = useState<ToolDefinition[]>([]);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingWorkflow, setEditingWorkflow] = useState<Workflow | null>(null);
  const [traceRun, setTraceRun] = useState<WorkflowExecution | null>(null);
  const [runInputOpen, setRunInputOpen] = useState(false);
  const [runInput, setRunInput] = useState('{}');
  const [runError, setRunError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [inputsFor, setInputsFor] = useState<Workflow | null>(null);
  const [draft, setDraft] = useState<WorkflowDraft | null>(null);
  const [templates, setTemplates] = useState<WorkflowTemplate[] | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiText, setAiText] = useState('');
  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [versions, setVersions] = useState<WorkflowVersion[] | null>(null);
  const [stepView, setStepView] = useState<'list' | 'canvas'>('list');
  const importRef = useRef<HTMLInputElement>(null);
  const traceWorkflowId = useRef<WorkflowId | null>(null);

  // Live run view: while the open run is running, keep refreshing it.
  const traceRunning = traceRun?.status === 'running';
  const traceRunId = traceRun?.id;
  useEffect(() => {
    if (!traceRunning || !traceRunId || traceWorkflowId.current == null) return;
    const workflowId = traceWorkflowId.current;
    const timer = setInterval(() => {
      workflowService.getWorkflowRun(workflowId, traceRunId).then(run => {
        setTraceRun(run);
        if (run.status !== 'running') {
          void fetchWorkflowRuns(workflowId);
          void fetchWorkflows();
        }
      }).catch(() => {});
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [traceRunning, traceRunId, fetchWorkflowRuns, fetchWorkflows]);

  const showRun = useCallback((workflowId: WorkflowId, run: WorkflowExecution) => {
    traceWorkflowId.current = workflowId;
    setTraceRun(run);
  }, []);

  useEffect(() => {
    // Editor metadata; failures leave the selectors empty rather than breaking the page.
    workflowService.getTools().then(setTools).catch(() => {});
  }, []);

  const openEditor = useCallback((workflow: Workflow | null, fromDraft: WorkflowDraft | null = null) => {
    setEditingWorkflow(workflow);
    setDraft(fromDraft);
    setEditorOpen(true);
    // Refresh tool availability in case apps were connected meanwhile.
    workflowService.getTools().then(setTools).catch(() => {});
  }, []);

  // /workflows?open=<id> (e.g. from "Turn into workflow" in chat) opens that workflow in the editor.
  const [searchParams, setSearchParams] = useSearchParams();
  const openId = searchParams.get('open');
  const missedIn = useRef<Workflow[] | null>(null);
  useEffect(() => {
    if (!openId || loading) return;
    const target = workflows.find(w => String(w.id) === openId);
    if (!target) {
      // The first render precedes the initial fetch; give up only if a later list lacks it too.
      if (missedIn.current && missedIn.current !== workflows) setSearchParams({}, { replace: true });
      else missedIn.current = workflows;
      return;
    }
    setSearchParams({}, { replace: true });
    selectWorkflow(target);
    openEditor(target);
  }, [openId, workflows, loading, selectWorkflow, openEditor, setSearchParams]);

  const handleSave = useCallback(async (data: WorkflowSaveData): Promise<string | null> => {
    try {
      const saved = editingWorkflow
        ? await updateWorkflow({ id: editingWorkflow.id, ...data, enabled: data.isActive })
        : await createWorkflow({ ...data, enabled: data.isActive });
      selectWorkflow(saved);
      void fetchWorkflowRuns(saved.id);
      setEditorOpen(false);
      setEditingWorkflow(null);
      return null;
    } catch (err) {
      return getErrorMessage(err);
    }
  }, [editingWorkflow, createWorkflow, updateWorkflow, selectWorkflow, fetchWorkflowRuns]);

  const handleToggleActive = useCallback(async (workflow: Workflow) => {
    try {
      await updateWorkflow({ id: workflow.id, isActive: !workflow.isActive, enabled: !workflow.isActive });
    } catch (err) {
      setRunError(getErrorMessage(err));
    }
  }, [updateWorkflow]);

  const handleDelete = useCallback(async (id: WorkflowId) => {
    if (window.confirm('Delete this workflow and its run history?')) {
      await deleteWorkflow(id).catch(() => {});
    }
  }, [deleteWorkflow]);

  const handleSelect = useCallback((workflow: Workflow) => {
    selectWorkflow(workflow);
    void fetchWorkflowRuns(workflow.id);
  }, [selectWorkflow, fetchWorkflowRuns]);

  /** Starts the workflow and opens the live run view; resolves to an error message, or null when it started. */
  const runNow = useCallback(async (workflow: Workflow, input: Record<string, unknown>): Promise<string | null> => {
    try {
      const run = await workflowService.startRun(workflow.id, { input_data: input });
      if (currentWorkflow?.id !== workflow.id) selectWorkflow(workflow);
      showRun(workflow.id, { ...run, events: [], trace: [] });
      return null;
    } catch (err) {
      return getErrorMessage(err);
    }
  }, [currentWorkflow, selectWorkflow, showRun]);

  const cancelTraceRun = useCallback(() => {
    if (!traceRun || traceWorkflowId.current == null) return;
    workflowService.cancelRun(traceWorkflowId.current, traceRun.id).catch(err => setRunError(getErrorMessage(err)));
  }, [traceRun]);

  const rerunTraceRun = useCallback(async () => {
    if (!traceRun || traceWorkflowId.current == null) return;
    try {
      const run = await workflowService.rerunFromFailure(traceWorkflowId.current, traceRun.id);
      showRun(traceWorkflowId.current, { ...run, events: [], trace: [] });
    } catch (err) {
      setRunError(getErrorMessage(err));
    }
  }, [traceRun, showRun]);

  const adopt = useCallback(async (created: Workflow) => {
    await fetchWorkflows();
    selectWorkflow(created);
    void fetchWorkflowRuns(created.id);
  }, [fetchWorkflows, selectWorkflow, fetchWorkflowRuns]);

  const handleImport = useCallback(async (file: File) => {
    setRunError(null);
    try {
      await adopt(await workflowService.importWorkflow(JSON.parse(await file.text())));
    } catch (err) {
      setRunError(`Import failed: ${getErrorMessage(err)}`);
    }
  }, [adopt]);

  const handleExport = useCallback(async (workflow: Workflow) => {
    try {
      const data = await workflowService.exportWorkflow(workflow.id);
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
      const link = Object.assign(document.createElement('a'), { href: url, download: `${workflow.name.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}.nexus.json` });
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setRunError(getErrorMessage(err));
    }
  }, []);

  const handleDraft = useCallback(async () => {
    setAiBusy(true);
    setAiError(null);
    try {
      const drafted = await workflowService.draft(aiText);
      setAiOpen(false);
      setAiText('');
      openEditor(null, drafted);
    } catch (err) {
      setAiError(getErrorMessage(err));
    } finally {
      setAiBusy(false);
    }
  }, [aiText, openEditor]);

  /** One-click run: asks for the manual trigger's inputs first when it has any. */
  const handleExecute = useCallback(async (workflow: Workflow, input?: Record<string, unknown>) => {
    setRunError(null);
    if (input === undefined && manualInputs(workflow).length > 0) {
      setInputsFor(workflow);
      return;
    }
    const failure = await runNow(workflow, input ?? {});
    if (failure) setRunError(failure);
  }, [runNow]);

  const handleRunWithInput = useCallback(async () => {
    if (!currentWorkflow) return;
    let input: unknown;
    try {
      input = JSON.parse(runInput || '{}');
    } catch {
      setRunError('Input must be valid JSON');
      return;
    }
    if (typeof input !== 'object' || input === null || Array.isArray(input)) {
      setRunError('Input must be a JSON object');
      return;
    }
    setRunInputOpen(false);
    await handleExecute(currentWorkflow, input as Record<string, unknown>);
  }, [currentWorkflow, runInput, handleExecute]);

  const webhookUrl = currentWorkflow?.trigger_config?.webhook_path
    ? `${api.getBaseUrl()}${currentWorkflow.trigger_config.webhook_path}`
    : null;

  const traceEntries: ExecutionTraceEntry[] = traceRun?.trace ?? traceRun?.events ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-nexus-text">Workflows</h1>
          <p className="text-nexus-text-secondary mt-1">Automate multi-step work with tools from your MCP servers</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 justify-end">
          <Button variant="secondary" size="sm" className="gap-1.5" onClick={() => workflowService.getTemplates().then(setTemplates).catch(err => setRunError(getErrorMessage(err)))}>
            <LayoutTemplate className="w-4 h-4" /> Templates
          </Button>
          <Button variant="secondary" size="sm" className="gap-1.5" onClick={() => { setAiError(null); setAiOpen(true); }}>
            <Sparkles className="w-4 h-4" /> Describe with AI
          </Button>
          <Button variant="secondary" size="sm" className="gap-1.5" onClick={() => importRef.current?.click()}>
            <Upload className="w-4 h-4" /> Import
          </Button>
          <input ref={importRef} type="file" accept=".json,application/json" className="hidden" aria-label="Import workflow file"
            onChange={(e) => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void handleImport(file); }} />
          <Button variant="primary" onClick={() => openEditor(null)} className="gap-1.5">
            <Plus className="w-4 h-4" /> New Workflow
          </Button>
        </div>
      </div>

      {(error || runError) && (
        <Card className="p-4 border-nexus-danger/30 bg-red-500/5">
          <div className="flex items-center gap-2 text-nexus-danger">
            <AlertCircle className="w-5 h-5 flex-shrink-0" />
            <span>{runError || error?.message}</span>
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1">
          <WorkflowList
            workflows={workflows}
            selectedWorkflow={currentWorkflow}
            onSelect={handleSelect}
            onToggleActive={(workflow) => void handleToggleActive(workflow)}
            onCreate={() => openEditor(null)}
            onEdit={openEditor}
            onDelete={handleDelete}
            onExecute={(wf) => void handleExecute(wf)}
            loading={loading}
          />
        </div>

        <div className="lg:col-span-2 space-y-6">
          {currentWorkflow ? (
            <>
              <Card>
                <div className="p-4 border-b border-nexus-border flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-nexus-text truncate">{currentWorkflow.name}</h3>
                      <span className={cn('px-2 py-0.5 rounded text-xs font-medium', TONE_STYLES[runState(currentWorkflow).tone])}
                        title={runState(currentWorkflow).label === 'Manual' ? 'Runs only when you start it' : undefined}>
                        {runState(currentWorkflow).label}
                      </span>
                    </div>
                    {currentWorkflow.description && <p className="text-sm text-nexus-text-secondary mt-1">{currentWorkflow.description}</p>}
                    <p className="text-xs text-nexus-text-muted mt-1 flex items-center gap-1"><Zap className="w-3 h-3" />{describeTrigger(currentWorkflow)}</p>
                    {currentWorkflow.trigger_status && (
                      <p className={cn('text-xs mt-0.5', currentWorkflow.trigger_status.last_error ? 'text-nexus-danger' : 'text-nexus-text-muted')}>
                        {currentWorkflow.trigger_status.last_checked_at
                          ? `Last checked ${formatRelativeTime(currentWorkflow.trigger_status.last_checked_at)}`
                          : 'Not checked yet'}
                        {currentWorkflow.trigger_status.last_error && ` · ${currentWorkflow.trigger_status.last_error}`}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <Button variant="primary" size="sm" onClick={() => void handleExecute(currentWorkflow)} className="gap-1.5">
                      <Play className="w-4 h-4" /> Run
                    </Button>
                    <Button variant="secondary" size="sm" onClick={() => { setRunError(null); setRunInputOpen(true); }}>
                      Run with input
                    </Button>
                    {runState(currentWorkflow).automatic && (
                      <Button variant="secondary" size="sm" onClick={() => void handleToggleActive(currentWorkflow)} className="gap-1.5">
                        {currentWorkflow.isActive ? <><Square className="w-4 h-4" /> Stop</> : <><Play className="w-4 h-4" /> Start</>}
                      </Button>
                    )}
                    <Button variant="secondary" size="sm" onClick={() => openEditor(currentWorkflow)} className="gap-1.5">
                      <Edit3 className="w-4 h-4" /> Edit
                    </Button>
                    <Button variant="ghost" size="sm" aria-label="Version history" title="Version history"
                      onClick={() => workflowService.getVersions(currentWorkflow.id).then(setVersions).catch(err => setRunError(getErrorMessage(err)))}>
                      <History className="w-4 h-4" />
                    </Button>
                    <Button variant="ghost" size="sm" aria-label="Export" title="Export as JSON" onClick={() => void handleExport(currentWorkflow)}>
                      <Download className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
                <div className="p-4 space-y-3">
                  {webhookUrl && (
                    <div>
                      <p className="text-xs font-medium text-nexus-text-secondary mb-1">
                        {currentWorkflow.trigger_config?.type === 'app_event' ? 'Point the app\'s webhook here (requires NEXUS_WEBHOOK_TOKEN or NEXUS_GITHUB_WEBHOOK_SECRET)' : 'POST to this URL to run the workflow (keep it secret)'}
                      </p>
                      <div className="flex items-center gap-2">
                        <code className="flex-1 text-xs bg-nexus-bg-tertiary border border-nexus-border rounded px-2 py-1.5 truncate">{webhookUrl}</code>
                        <Button variant="ghost" size="sm" aria-label="Copy URL" onClick={() => {
                          navigator.clipboard.writeText(webhookUrl).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }).catch(() => {});
                        }}>
                          <Copy className="w-4 h-4" />{copied && <span className="text-xs ml-1">Copied</span>}
                        </Button>
                      </div>
                    </div>
                  )}
                  {currentWorkflow.warnings && currentWorkflow.warnings.length > 0 && (
                    <ul className="text-xs text-nexus-warning space-y-1">
                      {currentWorkflow.warnings.map(w => <li key={w}>⚠ {w}</li>)}
                    </ul>
                  )}
                  <div className="flex gap-1" role="radiogroup" aria-label="Show steps as">
                    {(['list', 'canvas'] as const).map(view => (
                      <button key={view} type="button" role="radio" aria-checked={stepView === view} onClick={() => setStepView(view)}
                        className={cn('px-2.5 py-1 rounded-md text-xs', stepView === view ? 'bg-nexus-accent-dim text-nexus-accent' : 'text-nexus-text-secondary hover:bg-nexus-bg-tertiary')}>
                        {view === 'list' ? 'Steps' : 'Canvas'}
                      </button>
                    ))}
                  </div>
                  {stepView === 'canvas' ? <WorkflowCanvas nodes={currentWorkflow.nodes} edges={currentWorkflow.edges} /> : (
                  <ol className="flex flex-wrap gap-2">
                    {currentWorkflow.nodes.map(node => (
                      <li key={node.id} className="px-3 py-1 bg-nexus-bg-tertiary border border-nexus-border rounded-full text-sm">
                        {NODE_ICONS[node.type] ?? '⚙️'} {node.name}
                        {node.type === 'action' && typeof node.config?.tool === 'string' && <span className="text-nexus-text-muted"> · {node.config.tool}</span>}
                      </li>
                    ))}
                    {currentWorkflow.nodes.length === 0 && <li className="text-sm text-nexus-text-muted">No steps yet. Edit the workflow to add some.</li>}
                  </ol>
                  )}
                </div>
              </Card>

              <Card>
                <div className="p-4 border-b border-nexus-border flex items-center gap-2">
                  <History className="w-4 h-4 text-nexus-text-secondary" />
                  <h3 className="font-semibold text-nexus-text">Run history</h3>
                  <span className="text-xs text-nexus-text-muted">{runsLoading ? 'Loading…' : `${runs.length} run(s)`}</span>
                </div>
                {runs.length === 0 ? (
                  <div className="p-6 text-center text-sm text-nexus-text-muted">No runs yet.</div>
                ) : (
                  <ul className="p-4 space-y-2">
                    {runs.map(run => (
                      <li key={run.id}>
                        <button onClick={() => showRun(currentWorkflow.id, run)} className="w-full text-left flex items-center justify-between gap-3 p-3 bg-nexus-bg-tertiary/50 border border-nexus-border rounded-lg hover:bg-nexus-bg-tertiary">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className={cn('px-2 py-0.5 rounded text-xs font-medium', STATUS_CLASSES[run.status] ?? 'bg-gray-500/15 text-gray-400')}>{run.status}</span>
                              <span className="text-xs text-nexus-text-muted">{formatRelativeTime(run.startedAt)}</span>
                              {typeof run.input_data?.trigger === 'object' && run.input_data?.trigger !== null && (
                                <span className="text-xs text-nexus-text-muted">· {String((run.input_data.trigger as Record<string, unknown>).type)}</span>
                              )}
                            </div>
                            {run.error && <p className="text-xs text-nexus-danger mt-1 truncate">{run.error}</p>}
                          </div>
                          <span className="text-xs text-nexus-accent flex-shrink-0">View trace</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </>
          ) : (
            <Card className="h-[400px] flex items-center justify-center">
              <div className="text-center text-nexus-text-muted">
                <Zap className="w-12 h-12 mx-auto text-nexus-text-muted/50 mb-3" />
                <h3 className="text-lg font-medium text-nexus-text mb-1">Select a workflow</h3>
                <p className="text-sm">Choose a workflow from the list or create a new one</p>
              </div>
            </Card>
          )}
        </div>
      </div>

      <Modal open={editorOpen} onClose={() => setEditorOpen(false)} title={editingWorkflow ? 'Edit Workflow' : 'Create Workflow'} size="xl">
        {editorOpen && (
          <WorkflowBuilder
            key={editingWorkflow?.id ?? (draft ? 'draft' : 'new')}
            workflow={editingWorkflow}
            draft={draft}
            onSave={handleSave}
            onCancel={() => setEditorOpen(false)}
            tools={tools}
            llmProviders={llmProviders}
          />
        )}
      </Modal>

      {inputsFor && (
        <RunInputsModal
          open
          title={`Run ${inputsFor.name}`}
          inputs={manualInputs(inputsFor)}
          onClose={() => setInputsFor(null)}
          onSubmit={async (values) => {
            const failure = await runNow(inputsFor, values);
            if (!failure) setInputsFor(null);
            return failure;
          }}
        />
      )}

      <Modal open={runInputOpen} onClose={() => setRunInputOpen(false)} title="Run with input" size="md">
        <div className="space-y-3">
          <p className="text-sm text-nexus-text-secondary">JSON object available to steps as <code className="text-nexus-accent">{'{{ input.<key> }}'}</code>.</p>
          <textarea rows={8} value={runInput} onChange={(e) => setRunInput(e.target.value)} className="w-full font-mono text-sm px-3 py-2 rounded-lg bg-nexus-bg-tertiary border border-nexus-border text-nexus-text" />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setRunInputOpen(false)}>Cancel</Button>
            <Button variant="primary" size="sm" onClick={() => void handleRunWithInput()} className="gap-1.5"><Play className="w-4 h-4" /> Run</Button>
          </div>
        </div>
      </Modal>

      <Modal
        open={traceRun !== null}
        onClose={() => setTraceRun(null)}
        title={traceRun ? `Run ${traceRun.status}${traceRun.error ? ` — ${traceRun.error}` : ''}` : 'Run'}
        size="xl"
      >
        {traceRun && (
          <div className="space-y-3">
            {(traceRun.status === 'running' || traceRun.status === 'failed') && (
              <div className="flex items-center gap-2">
                {traceRun.status === 'running' && (
                  <>
                    <span className="text-xs text-nexus-text-secondary animate-pulse">Running…</span>
                    <Button variant="secondary" size="sm" className="gap-1.5" onClick={cancelTraceRun}><Square className="w-3.5 h-3.5" /> Cancel run</Button>
                  </>
                )}
                {traceRun.status === 'failed' && (
                  <Button variant="secondary" size="sm" className="gap-1.5" onClick={() => void rerunTraceRun()}>
                    <RotateCcw className="w-3.5 h-3.5" /> Re-run from failed step
                  </Button>
                )}
              </div>
            )}
            <ExecutionTrace trace={traceEntries} autoScroll={traceRun.status === 'running'} />
          </div>
        )}
      </Modal>

      <Modal open={templates !== null} onClose={() => setTemplates(null)} title="Start from a template" size="lg">
        <ul className="space-y-2">
          {(templates ?? []).map(t => (
            <li key={t.id} className="flex items-center gap-3 p-3 border border-nexus-border rounded-lg">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-nexus-text">{t.name}</p>
                <p className="text-xs text-nexus-text-muted">{t.description}</p>
              </div>
              <Button size="sm" onClick={async () => {
                try {
                  const created = await workflowService.createFromTemplate(t.id);
                  setTemplates(null);
                  await adopt(created);
                  openEditor(created);
                } catch (err) {
                  setRunError(getErrorMessage(err));
                }
              }}>Use</Button>
            </li>
          ))}
        </ul>
      </Modal>

      <Modal open={aiOpen} onClose={() => !aiBusy && setAiOpen(false)} title="Describe your workflow" size="md">
        <div className="space-y-3">
          <textarea rows={5} value={aiText} onChange={(e) => setAiText(e.target.value)} aria-label="Workflow description"
            placeholder="Every weekday at 9am, list my open GitHub issues and post a summary to Slack"
            className="w-full px-3 py-2 rounded-lg bg-nexus-bg-tertiary border border-nexus-border text-sm text-nexus-text" />
          <p className="text-xs text-nexus-text-muted">The AI drafts the trigger and steps using your connected MCP servers. You review it in the builder before saving.</p>
          {aiError && <p className="text-sm text-nexus-danger" role="alert">{aiError}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setAiOpen(false)} disabled={aiBusy}>Cancel</Button>
            <Button size="sm" className="gap-1.5" onClick={() => void handleDraft()} loading={aiBusy} disabled={aiBusy || !aiText.trim()}>
              <Sparkles className="w-4 h-4" /> Draft it
            </Button>
          </div>
        </div>
      </Modal>

      <Modal open={versions !== null} onClose={() => setVersions(null)} title="Version history" size="md">
        {versions && versions.length === 0 ? (
          <p className="text-sm text-nexus-text-muted">No earlier versions yet. A version is saved every time you edit the workflow.</p>
        ) : (
          <ul className="space-y-2">
            {(versions ?? []).map(v => (
              <li key={v.version} className="flex items-center gap-3 p-2 border border-nexus-border rounded-lg">
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-nexus-text">v{v.version} · {v.name}</p>
                  <p className="text-xs text-nexus-text-muted">{v.steps} step(s) · saved {formatRelativeTime(v.saved_at.endsWith('Z') ? v.saved_at : `${v.saved_at}Z`)}</p>
                </div>
                <Button size="sm" variant="secondary" onClick={async () => {
                  if (!currentWorkflow || !window.confirm(`Restore v${v.version}? The current version is kept in history.`)) return;
                  try {
                    await adopt(await workflowService.restoreVersion(currentWorkflow.id, v.version));
                    setVersions(null);
                  } catch (err) {
                    setRunError(getErrorMessage(err));
                  }
                }}>Restore</Button>
              </li>
            ))}
          </ul>
        )}
      </Modal>
    </div>
  );
}
