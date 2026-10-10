export type McpTransport = 'stdio' | 'http';
export type McpStatus = 'connecting' | 'needs_auth' | 'connected' | 'error' | 'stopped';

export interface McpTool {
  name: string;
  remote_name: string;
  description: string;
  policy: ToolPolicy;
  /** The server's own display title, if it gives one. */
  title?: string | null;
  read_only?: boolean | null;
  destructive?: boolean | null;
  /** Names of required parameters. */
  required?: string[];
}

export type ToolPolicy = 'allow' | 'ask' | 'block';

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
  blocked_tools: McpTool[];
  /** Overrides keyed by the server's own tool name; unset tools use the default policy. */
  tool_policies: Record<string, ToolPolicy>;
  /** The Marketplace listing it was installed from, if any. */
  registry_name?: string;
  /** Holds tokens from signing in to a hosted server. */
  signed_in: boolean;
  /** While status is needs_auth: the page to open to sign in. */
  auth_url: string | null;
  health: McpHealth | null;
}

export interface McpHealth {
  connected_since: string | null;
  calls: number;
  failures: number;
  last_call_at: string | null;
}

export interface McpLogs {
  events: { at: string; message: string }[];
  /** Tail of a local server's own error output. */
  stderr: string;
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
  tool_policies?: Record<string, ToolPolicy>;
}
