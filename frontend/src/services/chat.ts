import { api } from './api';
import type { AgentRunRequest, AgentRunResponse, AgentSession } from '../types/chat';

export const chatService = {
  async runAgent(request: AgentRunRequest): Promise<AgentRunResponse> {
    return api.post<AgentRunResponse>('/api/agent/run', request);
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
