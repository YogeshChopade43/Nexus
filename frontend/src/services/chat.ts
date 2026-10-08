import { api } from './api';
import type { AgentRunRequest, AgentRunResponse, AgentSession, AgentStreamEvent } from '../types/chat';
import type { Workflow } from '../types/workflow';

export const chatService = {
  async runAgent(request: AgentRunRequest): Promise<AgentRunResponse> {
    return api.post<AgentRunResponse>('/api/agent/run', request);
  },

  streamAgent(request: AgentRunRequest, onEvent: (event: AgentStreamEvent) => void): Promise<void> {
    return api.stream<AgentStreamEvent>('/api/agent/run/stream', request, onEvent);
  },

  answerApproval(sessionId: string, approved: boolean): Promise<AgentRunResponse> {
    return api.post<AgentRunResponse>(`/api/agent/sessions/${sessionId}/approval`, { approved });
  },

  toWorkflow(sessionId: string): Promise<Workflow> {
    return api.post<Workflow>(`/api/agent/sessions/${sessionId}/workflow`);
  },

  async createSession(title = ''): Promise<AgentSession> {
    return api.post<AgentSession>('/api/agent/sessions', { title });
  },

  async getSession(sessionId: string): Promise<AgentSession> {
    return api.get<AgentSession>(`/api/agent/sessions/${sessionId}`);
  },

  async listSessions(): Promise<AgentSession[]> {
    return api.get<AgentSession[]>('/api/agent/sessions');
  },

  async deleteSession(sessionId: string): Promise<void> {
    await api.delete(`/api/agent/sessions/${sessionId}`);
  },
};
