import { api } from './api';
import type { Activity, ActivityFilter, ActivityResponse, UndoPlan } from '../types/activity';

export interface Notifications {
  unread: number;
  items: (Activity & { unread: boolean })[];
}

export const activityService = {
  async getActivities(filter?: ActivityFilter): Promise<ActivityResponse> {
    const params: Record<string, string> = {};
    if (filter?.types?.length) params.types = filter.types.join(',');
    if (filter?.dateFrom) params.dateFrom = filter.dateFrom;
    if (filter?.dateTo) params.dateTo = filter.dateTo;
    if (filter?.limit) params.limit = String(filter.limit);
    if (filter?.offset) params.offset = String(filter.offset);

    return api.get<ActivityResponse>('/api/activity', params);
  },

  getNotifications: () => api.get<Notifications>('/api/activity/notifications'),
  markNotificationsRead: () => api.post<{ unread: number }>('/api/activity/notifications/read'),
  planUndo: (id: string) => api.post<UndoPlan>(`/api/activity/${id}/undo/plan`),
  runUndo: (id: string, plan: UndoPlan) =>
    api.post<{ undone: boolean }>(`/api/activity/${id}/undo/run`, { tool: plan.tool, arguments: plan.arguments }),
};