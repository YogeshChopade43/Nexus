import { useState, useCallback } from 'react';
import { activityService } from '../services/activity';
import type { Activity, ActivityFilter, ActivityResponse } from '../types/activity';

interface UseActivityReturn {
  activities: Activity[];
  loading: boolean;
  error: Error | null;
  hasMore: boolean;
  fetchActivities: (filter?: ActivityFilter, append?: boolean) => Promise<void>;
  fetchRecent: (limit?: number) => Promise<void>;
  clearActivities: () => void;
}

export function useActivity(): UseActivityReturn {
  const [activities, setActivities] = useState<Activity[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [hasMore, setHasMore] = useState(true);

  const fetchActivities = useCallback(async (filter?: ActivityFilter, append = false) => {
    setLoading(true);
    setError(null);
    try {
      const response: ActivityResponse = await activityService.getActivities(filter);
      if (append) {
        setActivities(prev => [...prev, ...response.activities]);
      } else {
        setActivities(response.activities);
      }
      setHasMore(response.hasMore);
    } catch (err) {
      setError(err as Error);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchRecent = useCallback(async (limit = 20) => {
    setLoading(true);
    setError(null);
    try {
      const response = await activityService.getActivities({ limit });
      setActivities(response.activities);
      setHasMore(response.hasMore);
    } catch (err) {
      const message = err instanceof Error
        ? err.message
        : typeof err === 'object' && err !== null && 'message' in err
          ? String((err as { message: unknown }).message)
          : 'Unknown error';
      setError(new Error(message));
    } finally {
      setLoading(false);
    }
  }, []);

  const clearActivities = useCallback(() => {
    setActivities([]);
    setHasMore(true);
  }, []);

  return {
    activities,
    loading,
    error,
    hasMore,
    fetchActivities,
    fetchRecent,
    clearActivities,
  };
}