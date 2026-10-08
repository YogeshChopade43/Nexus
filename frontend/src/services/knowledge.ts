import { api } from './api';
import type { Memory } from '../types/knowledge';

/** Facts the agent remembers across chats. Documents live in services/rag.ts. */
export const knowledgeService = {
  memories: () => api.get<Memory[]>('/api/knowledge/memories'),
  addMemory: (content: string) => api.post<Memory>('/api/knowledge/memories', { content }),
  removeMemory: (id: number) => api.delete<void>(`/api/knowledge/memories/${id}`),
};
