import { api, type ApiError } from './api';
import type { App, AppConnectionRequest, AppConnectionResponse, AppCategory, AppToolsResponse } from '../types/app';

export const appService = {
  async getApps(): Promise<App[]> {
    return api.get<App[]>('/api/apps');
  },

  async updateConnection(appId: string, request: AppConnectionRequest): Promise<AppConnectionResponse> {
    return api.post<AppConnectionResponse>(`/api/apps/${appId}/connection`, request);
  },

  async getCategories(): Promise<AppCategory[]> {
    const apps = await this.getApps();
    const categoryMap = new Map<string, number>();
    apps.forEach(app => {
      const cat = app.category || 'uncategorized';
      categoryMap.set(cat, (categoryMap.get(cat) || 0) + 1);
    });
    return Array.from(categoryMap.entries()).map(([id, count]) => ({
      id,
      name: id.charAt(0).toUpperCase() + id.slice(1),
      count,
    }));
  },

  async getAvailableTools(): Promise<string[]> {
    const response = await api.get<{ tools: string[] }>('/api/tools/available');
    return response.tools;
  },

  async getToolsForApp(appId: string): Promise<AppToolsResponse> {
    return api.get<AppToolsResponse>(`/api/tools/app/${appId}`);
  },
};

export { ApiError };
