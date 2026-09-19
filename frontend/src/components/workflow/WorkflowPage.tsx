import { useState, useCallback, useEffect } from 'react';
import { cn } from '../../lib/utils';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Modal } from '../ui/Modal';
import { WorkflowList } from './WorkflowList';
import { WorkflowEditor } from './WorkflowEditor';
import { ExecutionTrace } from './ExecutionTrace';
import { useWorkflows } from '../../hooks/useWorkflows';
import { appService } from '../../services/app';
import type { App } from '../../types/app';
import type { Workflow, WorkflowId, WorkflowNode, WorkflowEdge, WorkflowCreateRequest, WorkflowUpdateRequest } from '../../types/workflow';

const NODE_TYPES = [
  { type: 'trigger', name: 'Trigger', description: 'Start workflow on event', icon: '⚡' },
  { type: 'action', name: 'Action', description: 'Execute an operation', icon: '⚙️' },
  { type: 'condition', name: 'Condition', description: 'Branch based on logic', icon: '🔀' },
  { type: 'transform', name: 'Transform', description: 'Modify data', icon: '🔄' },
  { type: 'output', name: 'Output', description: 'Return result', icon: '📤' },
];

interface WorkflowSaveData {
  name: string;
  description: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  isActive: boolean;
}

export function WorkflowPage() {
  const {
    workflows,
    currentWorkflow,
    executions,
    runs,
    trace,
    loading,
    executing,
    runsLoading,
    traceLoading,
    error,
    createWorkflow,
    updateWorkflow,
    deleteWorkflow,
    selectWorkflow,
    executeWorkflow,
    fetchWorkflowRuns,
    fetchWorkflowTrace,
  } = useWorkflows();

  const [connectedApps, setConnectedApps] = useState<App[]>([]);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingWorkflow, setEditingWorkflow] = useState<Workflow | null>(null);
  const [traceWorkflow, setTraceWorkflow] = useState<Workflow | null>(null);

  useEffect(() => {
    appService.getApps().then(apps => {
      setConnectedApps(apps.filter(a => a.connected));
    }).catch(() => {});
  }, []);

  const handleCreate = useCallback(() => {
    setEditingWorkflow(null);
    setEditorOpen(true);
  }, []);

  const handleEdit = useCallback((workflow: Workflow) => {
    setEditingWorkflow(workflow);
    setEditorOpen(true);
  }, []);

  const handleSave = useCallback(async (data: WorkflowSaveData) => {
    try {
      if (editingWorkflow) {
        const updateRequest: WorkflowUpdateRequest = {
          id: editingWorkflow.id,
          name: data.name,
          description: data.description,
          nodes: data.nodes,
          edges: data.edges,
          isActive: data.isActive,
        };
        await updateWorkflow(updateRequest);
      } else {
        const createRequest: WorkflowCreateRequest = {
          name: data.name,
          description: data.description,
          nodes: data.nodes,
          edges: data.edges,
        };
        await createWorkflow(createRequest);
      }
      setEditorOpen(false);
      setEditingWorkflow(null);
    } catch (err) {
      console.error('Failed to save workflow:', err);
    }
  }, [editingWorkflow, createWorkflow, updateWorkflow]);

  const handleDelete = useCallback(async (id: WorkflowId) => {
    if (window.confirm('Are you sure you want to delete this workflow?')) {
      await deleteWorkflow(id);
    }
  }, [deleteWorkflow]);

  const handleSelect = useCallback((workflow: Workflow) => {
    selectWorkflow(workflow);
    void Promise.all([
      fetchWorkflowRuns(workflow.id),
      fetchWorkflowTrace(workflow.id),
    ]);
  }, [selectWorkflow, fetchWorkflowRuns, fetchWorkflowTrace]);

  const handleExecute = useCallback(async (workflow: Workflow) => {
    try {
      await executeWorkflow(workflow.id, {});
      await Promise.all([
        fetchWorkflowRuns(workflow.id),
        fetchWorkflowTrace(workflow.id),
      ]);
    } catch (err) {
      console.error('Failed to execute workflow:', err);
    }
  }, [executeWorkflow, fetchWorkflowRuns, fetchWorkflowTrace]);

  const handleViewTrace = useCallback((workflow: Workflow) => {
    setTraceWorkflow(workflow);
    void fetchWorkflowTrace(workflow.id);
  }, [fetchWorkflowTrace]);

  const displayedExecutions = runs.length > 0 ? runs : executions;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-nexus-text">Workflows</h1>
          <p className="text-nexus-text-secondary mt-1">Build and manage automated workflows</p>
        </div>
        <Button variant="primary" onClick={handleCreate} className="gap-1.5">
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          New Workflow
        </Button>
      </div>

      {error && (
        <Card className="p-4 border-nexus-danger/30 bg-red-500/5">
          <div className="flex items-center gap-2 text-nexus-danger">
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span>{error.message || 'Something went wrong'}</span>
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1">
          <WorkflowList
            workflows={workflows}
            selectedWorkflow={currentWorkflow}
            onSelect={handleSelect}
            onCreate={handleCreate}
            onEdit={handleEdit}
            onDelete={handleDelete}
            onExecute={handleExecute}
            loading={loading}
          />
        </div>

        <div className="lg:col-span-2 space-y-6">
          {currentWorkflow ? (
            <>
              <Card className="flex-1 min-h-[400px]">
                <div className="p-4 border-b-nexus-border border-b flex items-center justify-between">
                  <div>
                    <h3 className="font-semibold text-nexus-text">{currentWorkflow.name}</h3>
                    <p className="text-sm text-nexus-text-secondary">{currentWorkflow.description}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {currentWorkflow.isActive && (
                      <span className="px-2 py-0.5 bg-nexus-accent-dim text-nexus-accent rounded text-xs font-medium">Active</span>
                    )}
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => handleExecute(currentWorkflow)}
                      disabled={executing}
                      className="gap-1.5"
                    >
                      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <polygon points="5 3 19 12 5 21 5 3" />
                      </svg>
                      Execute
                    </Button>
                    <Button variant="secondary" size="sm" onClick={() => handleEdit(currentWorkflow)} className="gap-1.5">
                      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2-2v-7" />
                        <path d="M18.5 2.5a2.121 2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                      </svg>
                      Edit
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => handleViewTrace(currentWorkflow)}
                      disabled={traceLoading}
                      className="gap-1.5"
                    >
                      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                        <polyline points="22 4 12 14.01 9 11.01" />
                      </svg>
                      Trace
                    </Button>
                  </div>
                </div>
                <div className="p-4">
                  <div className="space-y-4">
                    <div>
                      <h4 className="font-medium text-nexus-text mb-2">Nodes ({currentWorkflow.nodes.length})</h4>
                      <div className="flex flex-wrap gap-2">
                        {currentWorkflow.nodes.map(node => (
                          <span key={node.id} className="px-3 py-1 bg-nexus-bg-tertiary border-nexus-border border rounded-full text-sm">
                            {node.type}: {node.name}
                            {node.type === 'trigger' && node.app_id && (() => {
                              const app = connectedApps.find(a => (a.app_id ?? a.id) === node.app_id);
                              return app ? ` · ${app.name}` : '';
                            })()}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div>
                      <h4 className="font-medium text-nexus-text mb-2">Connections ({currentWorkflow.edges.length})</h4>
                      <div className="space-y-1">
                        {currentWorkflow.edges.map(edge => (
                          <div key={edge.id} className="text-sm text-nexus-text-secondary font-mono">
                            {edge.source} → {edge.target}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </Card>

              <Card>
                <div className="p-4 border-b-nexus-border border-b flex items-center justify-between">
                  <div>
                    <h3 className="font-semibold text-nexus-text">Recent Executions</h3>
                    <p className="text-xs text-nexus-text-secondary mt-1">
                      {runsLoading ? 'Loading runs...' : `${displayedExecutions.length} run(s) returned by the backend`}
                    </p>
                  </div>
                </div>
                {displayedExecutions.length === 0 ? (
                  <div className="p-6 text-center text-sm text-nexus-text-muted">
                    No workflow runs have been recorded yet.
                  </div>
                ) : (
                  <div className="p-4 space-y-2">
                    {displayedExecutions.slice(0, 5).map(execution => (
                      <div key={execution.id} className="flex items-center justify-between p-3 bg-nexus-bg-tertiary/50 border-nexus-border border rounded-lg">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm truncate">{execution.id.slice(0, 8)}...</span>
                            <span className={cn(
                              'px-2 py-0.5 rounded text-xs font-medium flex-shrink-0',
                              execution.status === 'completed' && 'bg-green-500/15 text-green-400',
                              execution.status === 'running' && 'bg-blue-500/15 text-blue-400',
                              execution.status === 'failed' && 'bg-red-500/15 text-red-400',
                              execution.status === 'pending' && 'bg-amber-500/15 text-amber-400',
                              execution.status === 'cancelled' && 'bg-gray-500/15 text-gray-400',
                              execution.status === 'partial' && 'bg-amber-500/15 text-amber-400',
                              execution.status === 'skipped' && 'bg-gray-500/15 text-gray-400',
                            )}>
                              {execution.status}
                            </span>
                          </div>
                          <div className="text-xs text-nexus-text-muted mt-1">
                            Started: {new Date(execution.startedAt).toLocaleString()}
                            {execution.completedAt && ` • Completed: ${new Date(execution.completedAt).toLocaleString()}`}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </>
          ) : (
            <Card className="h-[500px] flex items-center justify-center">
              <div className="text-center text-nexus-text-muted">
                <svg className="w-16 h-16 mx-auto text-nexus-text-muted/50 mb-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
                </svg>
                <h3 className="text-lg font-medium text-nexus-text mb-1">Select a workflow</h3>
                <p className="text-sm">Choose a workflow from the list or create a new one</p>
              </div>
            </Card>
          )}
        </div>
      </div>

      <Modal open={editorOpen} onClose={() => setEditorOpen(false)} title={editingWorkflow ? 'Edit Workflow' : 'Create Workflow'} size="xl">
        <WorkflowEditor
          workflow={editingWorkflow}
          onSave={handleSave}
          onCancel={() => setEditorOpen(false)}
          availableNodeTypes={NODE_TYPES}
          connectedApps={connectedApps}
        />
      </Modal>

      <Modal
        open={traceWorkflow !== null}
        onClose={() => setTraceWorkflow(null)}
        title={traceWorkflow ? `Execution Trace: ${traceWorkflow.name}` : 'Execution Trace'}
        size="xl"
      >
        {traceWorkflow && <ExecutionTrace trace={trace.length > 0 ? trace : executions[0]?.trace || executions[0]?.events || []} />}
      </Modal>
    </div>
  );
}
