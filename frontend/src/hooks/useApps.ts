import { useState, useEffect, useCallback } from 'react';
import { appService } from '../services/app';
import type { App, AppCategory, AppConnectionRequest, ConnectorConfig } from '../types/app';

interface UseAppsReturn {
  apps: App[];
  categories: AppCategory[];
  total: number;
  loading: boolean;
  error: Error | null;
  fetchApps: () => Promise<void>;
  toggleConnection: (app: App, connect: boolean, config?: ConnectorConfig) => Promise<void>;
  configureConnection: (app: App, config: ConnectorConfig) => Promise<void>;
  refreshing: string | null;
  availableTools: string[];
  refreshAvailableTools: () => Promise<void>;
  toolsLoading: boolean;
  toolsError: Error | null;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'object' && error !== null && 'message' in error) {
    return String((error as { message: unknown }).message);
  }
  return 'Unknown error';
}

export function useApps(): UseAppsReturn {
  const [apps, setApps] = useState<App[]>([]);
  const [categories, setCategories] = useState<AppCategory[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [refreshing, setRefreshing] = useState<string | null>(null);
  const [availableTools, setAvailableTools] = useState<string[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [toolsError, setToolsError] = useState<Error | null>(null);

  const fetchApps = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await appService.getApps();
      setApps(data.map(app => ({
        ...app,
        connectionStatus: app.connected ? 'connected' : 'disconnected',
        connectionError: null,
      })));
      setTotal(data.length);
      const cats = await appService.getCategories();
      setCategories(cats);
    } catch (err) {
      setError(new Error(getErrorMessage(err)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchApps();
  }, [fetchApps]);

  const refreshAvailableTools = useCallback(async () => {
    setToolsLoading(true);
    setToolsError(null);
    try {
      const tools = await appService.getAvailableTools();
      setAvailableTools(tools);
    } catch (err) {
      setToolsError(new Error(getErrorMessage(err)));
    } finally {
      setToolsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshAvailableTools();
  }, [refreshAvailableTools]);

  const toggleConnection = useCallback(async (app: App, connect: boolean, config?: ConnectorConfig) => {
    const appId = app.app_id ?? app.id;
    setRefreshing(appId);
    setError(null);
    setApps(prev => prev.map(a =>
      (a.app_id ?? a.id) === appId
        ? { ...a, connectionStatus: connect ? 'connecting' : 'disconnected', connectionError: null }
        : a
    ));
    try {
      const request: AppConnectionRequest = {
        connected: connect,
        ...(connect && config ? { config } : {}),
      };
      const response = await appService.updateConnection(appId, request);
      setApps(prev => prev.map(a =>
        (a.app_id ?? a.id) === appId
          ? {
              ...a,
              enabled: response.enabled,
              connected: response.connected,
              connectionStatus: response.connected ? 'connected' : 'disconnected',
              connectionError: null,
            }
          : a
      ));
      await refreshAvailableTools();
    } catch (err) {
      const message = getErrorMessage(err);
      setApps(prev => prev.map(a =>
        (a.app_id ?? a.id) === appId
          ? { ...a, connected: app.connected, connectionStatus: 'error', connectionError: message }
          : a
      ));
      setError(new Error(message));
    } finally {
      setRefreshing(null);
    }
  }, [refreshAvailableTools]);

  const configureConnection = useCallback(async (app: App, config: ConnectorConfig) => {
    const appId = app.app_id ?? app.id;
    setRefreshing(appId);
    setError(null);
    setApps(prev => prev.map(a =>
      (a.app_id ?? a.id) === appId
        ? { ...a, connectionStatus: 'connecting', connectionError: null }
        : a
    ));
    try {
      const request: AppConnectionRequest = {
        connected: true,
        config,
      };
      const response = await appService.updateConnection(appId, request);
      setApps(prev => prev.map(a =>
        (a.app_id ?? a.id) === appId
          ? {
              ...a,
              enabled: response.enabled,
              connected: response.connected,
              connectionStatus: response.connected ? 'connected' : 'disconnected',
              connectionError: null,
            }
          : a
      ));
      await refreshAvailableTools();
    } catch (err) {
      const message = getErrorMessage(err);
      setApps(prev => prev.map(a =>
        (a.app_id ?? a.id) === appId
          ? { ...a, connectionStatus: 'error', connectionError: message }
          : a
      ));
      setError(new Error(message));
    } finally {
      setRefreshing(null);
    }
  }, [refreshAvailableTools]);

  return {
    apps,
    categories,
    total,
    loading,
    error,
    fetchApps,
    toggleConnection,
    configureConnection,
    refreshing,
    availableTools,
    refreshAvailableTools,
    toolsLoading,
    toolsError,
  };
}
