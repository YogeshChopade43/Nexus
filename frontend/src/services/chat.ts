import { api } from './api';
import type { AgentRunRequest, AgentRunResponse } from '../types/chat';

export const chatService = {
  async runAgent(request: AgentRunRequest): Promise<AgentRunResponse> {
    return api.post<AgentRunResponse>('/api/agent/run', request);
  },
};
