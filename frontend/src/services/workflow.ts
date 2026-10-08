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
  StepTestResult,
  WorkflowDraft,
  WorkflowNode,
  WorkflowTemplate,
  WorkflowVersion,
  AppWebhookSetup,
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

  /** Starts a run and returns at once with status "running"; poll getWorkflowRun for progress. */
  async startRun(id: WorkflowId, request: WorkflowRunRequest): Promise<WorkflowExecution> {
    return api.post<WorkflowExecution>(`/api/workflows/${id}/run?background=true`, request);
  },

  async cancelRun(id: WorkflowId, runId: string): Promise<void> {
    await api.post(`/api/workflows/${id}/runs/${runId}/cancel`);
  },

  async rerunFromFailure(id: WorkflowId, runId: string): Promise<WorkflowExecution> {
    return api.post<WorkflowExecution>(`/api/workflows/${id}/runs/${runId}/rerun`);
  },

  async testStep(body: { node: WorkflowNode; workflow_id?: WorkflowId; sample: Record<string, unknown> }): Promise<StepTestResult> {
    return api.post<StepTestResult>('/api/workflows/test-step', body);
  },

  async getVersions(id: WorkflowId): Promise<WorkflowVersion[]> {
    return api.get<WorkflowVersion[]>(`/api/workflows/${id}/versions`);
  },

  async restoreVersion(id: WorkflowId, version: number): Promise<Workflow> {
    return api.post<Workflow>(`/api/workflows/${id}/versions/${version}/restore`);
  },

  async exportWorkflow(id: WorkflowId): Promise<Record<string, unknown>> {
    return api.get<Record<string, unknown>>(`/api/workflows/${id}/export`);
  },

  async importWorkflow(data: unknown): Promise<Workflow> {
    return api.post<Workflow>('/api/workflows/import', data);
  },

  async getTemplates(): Promise<WorkflowTemplate[]> {
    return api.get<WorkflowTemplate[]>('/api/workflows/templates');
  },

  async createFromTemplate(templateId: string): Promise<Workflow> {
    return api.post<Workflow>(`/api/workflows/templates/${templateId}`);
  },

  async draft(description: string): Promise<WorkflowDraft> {
    return api.post<WorkflowDraft>('/api/workflows/draft', { description });
  },

  async getAppWebhookSetup(): Promise<AppWebhookSetup[]> {
    return api.get<AppWebhookSetup[]>('/api/webhooks/apps');
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
