import { api } from './api';
import type {
  Workflow,
  WorkflowExecution,
  WorkflowCreateRequest,
  WorkflowUpdateRequest,
  WorkflowRunRequest,
  WorkflowRunsResponse,
  WorkflowTraceResponse,
  WorkflowId,
  ToolDefinition,
  TriggerTypeInfo,
  RecurrenceSettings,
} from '../types/workflow';

export const workflowService = {
  async getWorkflows(): Promise<Workflow[]> {
    return api.get<Workflow[]>('/api/workflows');
  },

  async getWorkflow(id: WorkflowId): Promise<Workflow> {
    return api.get<Workflow>(`/api/workflows/${id}`);
  },

  async createWorkflow(request: WorkflowCreateRequest): Promise<Workflow> {
    return api.post<Workflow>('/api/workflows', request);
  },

  async updateWorkflow(request: WorkflowUpdateRequest): Promise<Workflow> {
    return api.patch<Workflow>(`/api/workflows/${request.id}`, request);
  },

  async deleteWorkflow(id: WorkflowId): Promise<void> {
    return api.delete<void>(`/api/workflows/${id}`);
  },

  async runWorkflow(id: WorkflowId, request: WorkflowRunRequest): Promise<WorkflowExecution> {
    return api.post<WorkflowExecution>(`/api/workflows/${id}/run`, request);
  },

  async getWorkflowRuns(id: WorkflowId): Promise<WorkflowRunsResponse> {
    return api.get<WorkflowRunsResponse>(`/api/workflows/${id}/runs`);
  },

  async getWorkflowRun(id: WorkflowId, runId: string): Promise<WorkflowExecution> {
    return api.get<WorkflowExecution>(`/api/workflows/${id}/runs/${runId}`);
  },

  async getTools(): Promise<ToolDefinition[]> {
    const response = await api.get<{ tools: ToolDefinition[] }>('/api/tools/', { limit: '500' });
    return response.tools;
  },

  async previewRecurrence(settings: Partial<RecurrenceSettings>): Promise<{ next_runs: string[] }> {
    return api.post<{ next_runs: string[] }>('/api/workflows/recurrence/preview', settings);
  },

  async getTriggerTypes(): Promise<TriggerTypeInfo[]> {
    return api.get<TriggerTypeInfo[]>('/api/workflows/triggers');
  },

  async getWorkflowTrace(id: WorkflowId): Promise<WorkflowTraceResponse> {
    return api.get<WorkflowTraceResponse>(`/api/workflows/${id}/trace`);
  },
};
