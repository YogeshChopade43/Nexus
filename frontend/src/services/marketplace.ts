import { api } from './api';
import type { McpServer } from '../types/mcp';
import type { MarketCard, MarketItem, MarketKind, MarketSort, SyncStatus } from '../types/marketplace';

export const PAGE_SIZE = 30;

/** A listing's logo, fetched and cached by the backend (own icon, GitHub avatar or site favicon). */
export const iconUrl = (name: string) => `${api.getBaseUrl()}/api/marketplace/icon?name=${encodeURIComponent(name)}`;

export const marketplaceService = {
  list: (params: { q: string; kind: MarketKind; sort: MarketSort; offset: number; official: boolean }) =>
    api.get<{ items: MarketCard[]; status: SyncStatus }>('/api/marketplace', {
      q: params.q, kind: params.kind, sort: params.sort, offset: String(params.offset), limit: String(PAGE_SIZE),
      ...(params.official ? { official: 'true' } : {}),
    }),
  featured: () => api.get<{ items: MarketCard[] }>('/api/marketplace/featured'),
  item: (name: string) => api.get<MarketItem>('/api/marketplace/item', { name }),
  install: (name: string, values: Record<string, string>) =>
    api.post<McpServer>('/api/marketplace/install', { name, values }),
  refresh: () => api.post<{ started: boolean }>('/api/marketplace/refresh'),
  status: () => api.get<SyncStatus>('/api/marketplace/status'),
};
