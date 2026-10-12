import { api } from './api';
import type { McpLogs, McpServer, McpServerInput } from '../types/mcp';

export const mcpService = {
  list: () => api.get<McpServer[]>('/api/mcp/servers/'),
  get: (id: number) => api.get<McpServer>(`/api/mcp/servers/${id}`),
  create: (input: McpServerInput) => api.post<McpServer>('/api/mcp/servers/', input),
  update: (id: number, input: Partial<McpServerInput>) => api.patch<McpServer>(`/api/mcp/servers/${id}`, input),
  restart: (id: number) => api.post<McpServer>(`/api/mcp/servers/${id}/restart`),
  remove: (id: number) => api.delete<void>(`/api/mcp/servers/${id}`),
  test: (id: number) => api.post<{ ok: boolean; message: string }>(`/api/mcp/servers/${id}/test`),
  logs: (id: number) => api.get<McpLogs>(`/api/mcp/servers/${id}/logs`),
  signOut: (id: number) => api.post<McpServer>(`/api/mcp/servers/${id}/sign-out`),
};
