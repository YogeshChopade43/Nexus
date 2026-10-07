export type McpTransport = 'stdio' | 'http';
export type McpStatus = 'connecting' | 'connected' | 'error' | 'stopped';

export interface McpTool {
  name: string;
  remote_name: string;
  description: string;
}

export interface McpServer {
  id: number;
  slug: string;
  name: string;
  transport: McpTransport;
  command: string;
  args: string[];
  /** Secret values are never returned; each key maps to "***". */
  env: Record<string, string>;
  url: string;
  headers: Record<string, string>;
  enabled: boolean;
  status: McpStatus;
  error: string | null;
  tools: McpTool[];
}

export interface McpServerInput {
  name: string;
  transport: McpTransport;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  headers?: Record<string, string>;
  enabled?: boolean;
}
