import type { McpServer, McpStatus } from './mcp';

/** A Marketplace listing (or, with name null, an installed server that isn't from the registry). */
export interface MarketCard {
  name: string | null;
  title: string;
  description: string;
  /** Readable: "notion.com" or "github.com/user". */
  publisher: string;
  /** The publisher proved to the registry that they own this domain (Featured listings may be GitHub accounts). */
  verified: boolean;
  /** From the app maker's own verified domain (matched automatically). */
  official: boolean;
  icon_url: string | null;
  updated_at: string | null;
  installed_server_id: number | null;
  /** Connection state of the installed server (null when not installed). */
  status: McpStatus | null;
}

/** One input of a listing's install form. */
export interface MarketField {
  key: string;
  label: string;
  description: string;
  required: boolean;
  secret: boolean;
  default: string;
}

export interface MarketItem extends MarketCard {
  version: string | null;
  repository_url: string | null;
  website_url: string | null;
  fields: MarketField[];
  /** Where installing connects; {placeholders} are the form's answers. */
  launch: { url: string; headers: Record<string, string> };
  installed: McpServer | null;
}

export interface SyncStatus {
  status: 'idle' | 'syncing' | 'error';
  count: number;
  last_synced_at: string | null;
  error: string | null;
}

export type MarketKind = 'all' | 'installed';
export type MarketSort = 'relevance' | 'updated';
