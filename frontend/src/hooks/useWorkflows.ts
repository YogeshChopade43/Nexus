import { useState, useCallback, useEffect } from 'react';
import { workflowService } from '../services/workflow';
import type {
  ExecutionTraceEntry,
  Workflow,
  WorkflowExecution,
  WorkflowCreateRequest,
  WorkflowId,
  WorkflowRunRequest,
  WorkflowUpdateRequest,
} from '../types/workflow';

interface UseWorkflowsReturn {
  workflows: Workflow[];
  currentWorkflow: Workflow | null;
  executions: WorkflowExecution[];
  runs: WorkflowExecution[];
  trace: ExecutionTraceEntry[];
  loading: boolean;
  error: Error | null;
  executing: boolean;
  runsLoading: boolean;
  traceLoading: boolean;
  fetchWorkflows: () => Promise<void>;
  fetchWorkflow: (id: WorkflowId) => Promise<Workflow>;
  fetchWorkflowRuns: (id: WorkflowId) => Promise<void>;
  fetchWorkflowTrace: (id: WorkflowId) => Promise<void>;
  createWorkflow: (request: WorkflowCreateRequest) => Promise<Workflow>;
  updateWorkflow: (request: WorkflowUpdateRequest) => Promise<Workflow>;
  deleteWorkflow: (id: WorkflowId) => Promise<void>;
  selectWorkflow: (workflow: Workflow | null) => void;
  executeWorkflow: (id: WorkflowId, input?: Record<string, unknown>) => Promise<WorkflowExecution>;
  clearExecutions: () => void;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'object' && error !== null && 'message' in error) {
    return String((error as { message: unknown }).message);
  }
  return 'Unknown error';
}

export function useWorkflows(): UseWorkflowsReturn {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [currentWorkflow, setCurrentWorkflow] = useState<Workflow | null>(null);
  const [executions, setExecutions] = useState<WorkflowExecution[]>([]);
  const [runs, setRuns] = useState<WorkflowExecution[]>([]);
  const [trace, setTrace] = useState<ExecutionTraceEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [executing, setExecuting] = useState(false);
  const [runsLoading, setRunsLoading] = useState(false);
  const [traceLoading, setTraceLoading] = useState(false);

  const fetchWorkflows = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await workflowService.getWorkflows();
      setWorkflows(data);
    } catch (err) {
      setError(new Error(getErrorMessage(err)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchWorkflows();
  }, [fetchWorkflows]);

  const fetchWorkflow = useCallback(async (id: WorkflowId): Promise<Workflow> => {
    setLoading(true);
    setError(null);
    try {
      const workflow = await workflowService.getWorkflow(id);
      setCurrentWorkflow(workflow);
      return workflow;
    } catch (err) {
      setError(new Error(getErrorMessage(err)));
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchWorkflowRuns = useCallback(async (id: WorkflowId) => {
    setRunsLoading(true);
    setError(null);
    try {
      const response = await workflowService.getWorkflowRuns(id);
      setRuns(response.runs);
    } catch (err) {
      setError(new Error(getErrorMessage(err)));
    } finally {
      setRunsLoading(false);
    }
  }, []);

  const fetchWorkflowTrace = useCallback(async (id: WorkflowId) => {
    setTraceLoading(true);
    setError(null);
    try {
      const response = await workflowService.getWorkflowTrace(id);
      setTrace(response.steps);
    } catch (err) {
      setError(new Error(getErrorMessage(err)));
    } finally {
      setTraceLoading(false);
    }
  }, []);

  const createWorkflow = useCallback(async (request: WorkflowCreateRequest): Promise<Workflow> => {
    setLoading(true);
    setError(null);
    try {
      const workflow = await workflowService.createWorkflow(request);
      setWorkflows(prev => [workflow, ...prev]);
      return workflow;
    } catch (err) {
      setError(new Error(getErrorMessage(err)));
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const updateWorkflow = useCallback(async (request: WorkflowUpdateRequest): Promise<Workflow> => {
    setLoading(true);
    setError(null);
    try {
      const workflow = await workflowService.updateWorkflow(request);
      setWorkflows(prev => prev.map(item => item.id === workflow.id ? workflow : item));
      if (currentWorkflow?.id === workflow.id) {
        setCurrentWorkflow(workflow);
      }
      return workflow;
    } catch (err) {
      setError(new Error(getErrorMessage(err)));
      throw err;
    } finally {
      setLoading(false);
    }
  }, [currentWorkflow]);

  const deleteWorkflow = useCallback(async (id: WorkflowId): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      await workflowService.deleteWorkflow(id);
      setWorkflows(prev => prev.filter(workflow => workflow.id !== id));
      if (currentWorkflow?.id === id) {
        setCurrentWorkflow(null);
      }
    } catch (err) {
      setError(new Error(getErrorMessage(err)));
      throw err;
    } finally {
      setLoading(false);
    }
  }, [currentWorkflow]);

  const selectWorkflow = useCallback((workflow: Workflow | null) => {
    setCurrentWorkflow(workflow);
    setExecutions([]);
    setRuns([]);
    setTrace([]);
  }, []);

  const executeWorkflow = useCallback(async (id: WorkflowId, input?: Record<string, unknown>): Promise<WorkflowExecution> => {
    setExecuting(true);
    setError(null);
    try {
      const request: WorkflowRunRequest = { input_data: input ?? {} };
      const execution = await workflowService.runWorkflow(id, request);
      setExecutions(prev => [execution, ...prev]);
      return execution;
    } catch (err) {
      setError(new Error(getErrorMessage(err)));
      throw err;
    } finally {
      setExecuting(false);
    }
  }, []);

  const clearExecutions = useCallback(() => {
    setExecutions([]);
  }, []);

  return {
    workflows,
    currentWorkflow,
    executions,
    runs,
    trace,
    loading,
    error,
    executing,
    runsLoading,
    traceLoading,
    fetchWorkflows,
    fetchWorkflow,
    fetchWorkflowRuns,
    fetchWorkflowTrace,
    createWorkflow,
    updateWorkflow,
    deleteWorkflow,
    selectWorkflow,
    executeWorkflow,
    clearExecutions,
  };
}
