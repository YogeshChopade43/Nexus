import { api } from './api';
import type { AgentRunRequest, AgentRunResponse, AgentSession, AgentStreamEvent, ChatSettings, QuestionAnswers } from '../types/chat';
import type { Workflow } from '../types/workflow';

type OnEvent = (event: AgentStreamEvent) => void;

export const chatService = {
  async runAgent(request: AgentRunRequest): Promise<AgentRunResponse> {
    return api.post<AgentRunResponse>('/api/agent/run', request);
  },

  streamAgent(request: AgentRunRequest, onEvent: OnEvent, signal?: AbortSignal): Promise<void> {
    return api.stream<AgentStreamEvent>('/api/agent/run/stream', request, onEvent, undefined, undefined, signal);
  },

  /** Approve or deny the waiting tool call; the rest of the reply streams like a normal one. */
  streamApproval(sessionId: string, approved: boolean, onEvent: OnEvent, signal?: AbortSignal): Promise<void> {
    return api.stream<AgentStreamEvent>(`/api/agent/sessions/${sessionId}/approval/stream`, { approved }, onEvent, undefined, undefined, signal);
  },

  /** Answer the question cards; the rest of the reply streams like a normal one. */
  streamAnswers(sessionId: string, answers: QuestionAnswers, onEvent: OnEvent, signal?: AbortSignal): Promise<void> {
    return api.stream<AgentStreamEvent>(`/api/agent/sessions/${sessionId}/answer/stream`, { answers }, onEvent, undefined, undefined, signal);
  },

  /** Drop the last user message and everything after it; returns that message's text. */
  rewind(sessionId: string): Promise<{ message: string }> {
    return api.post<{ message: string }>(`/api/agent/sessions/${sessionId}/rewind`);
  },

  saveSettings(sessionId: string, settings: ChatSettings): Promise<ChatSettings> {
    return api.put<ChatSettings>(`/api/agent/sessions/${sessionId}/settings`, settings);
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

  async listSessions(query = ''): Promise<AgentSession[]> {
    return api.get<AgentSession[]>('/api/agent/sessions', query ? { q: query } : undefined);
  },

  async deleteSession(sessionId: string): Promise<void> {
    await api.delete(`/api/agent/sessions/${sessionId}`);
  },
};
