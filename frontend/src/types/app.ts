export type ConnectionStatus = 'connected' | 'disconnected' | 'connecting' | 'error';

export type ConnectorConfig = Record<string, string>;

export interface App {
  id: string;
  app_id?: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  enabled: boolean;
  connected: boolean;
  capabilities: string[];
  config?: Record<string, unknown>;
  createdAt?: string;
  updatedAt?: string;
  connectionStatus?: ConnectionStatus;
  connectionError?: string | null;
}

export interface AppConnectionRequest {
  connected?: boolean;
  config?: ConnectorConfig;
}

export interface AppConnectionResponse {
  app_id: string;
  enabled: boolean;
  connected: boolean;
  message: string;
}

export interface AppCategory {
  id: string;
  name: string;
  count: number;
}

export interface ToolInfo {
  tool_name: string;
  app_id: string;
  description: string;
}

export interface AppToolsResponse {
  app_id: string;
  connected: boolean;
  tools: string[];
}
