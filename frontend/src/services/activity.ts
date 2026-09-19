import { api } from './api';
import type { ActivityFilter, ActivityResponse } from '../types/activity';

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
};