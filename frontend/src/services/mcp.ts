import { api } from './api';
import type { McpServer, McpServerInput } from '../types/mcp';

export const mcpService = {
  list: () => api.get<McpServer[]>('/api/mcp/servers/'),
  create: (input: McpServerInput) => api.post<McpServer>('/api/mcp/servers/', input),
  update: (id: number, input: Partial<McpServerInput>) => api.patch<McpServer>(`/api/mcp/servers/${id}`, input),
  restart: (id: number) => api.post<McpServer>(`/api/mcp/servers/${id}/restart`),
  remove: (id: number) => api.delete<void>(`/api/mcp/servers/${id}`),
};
