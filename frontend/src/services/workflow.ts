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

  async getWorkflowTrace(id: WorkflowId): Promise<WorkflowTraceResponse> {
    return api.get<WorkflowTraceResponse>(`/api/workflows/${id}/trace`);
  },
};
