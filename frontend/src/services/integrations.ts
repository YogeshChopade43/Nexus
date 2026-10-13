import { api } from './api';
import { mcpService } from './mcp';
import type { McpServer, McpTool } from '../types/mcp';

export interface IntegrationField {
  name: string;
  label: string;
  type: 'text' | 'password' | 'email' | 'url' | 'number';
  required: boolean;
  default: string | number | null;
  help: string;
  advanced: boolean;
}

export interface IntegrationKind {
  id: string;
  title: string;
  description: string;
  /** A Lucide icon name. */
  icon: string;
  fields: IntegrationField[];
  /** Google: the address to register in the user's own OAuth client. */
  redirect_uri?: string;
  manifest?: string;  // Slack: the app manifest to paste into "Create an app"
}

export interface Integration {
  id: number;
  kind: string;
  name: string;
  slug: string;
  enabled: boolean;
  created_at: string;
  /** Non-secret settings (secrets never come back). */
  settings: Record<string, unknown>;
  status: 'connected' | 'stopped' | 'needs_auth';
  /** What the connection check found, right after connecting. */
  message: string;
  tools: McpTool[];
}

export const integrationService = {
  kinds: () => api.get<IntegrationKind[]>('/api/integrations/kinds'),
  list: () => api.get<Integration[]>('/api/integrations'),
  create: (kind: string, name: string, config: Record<string, unknown>) =>
    api.post<Integration>('/api/integrations', { kind, name, config }),
  update: (id: number, changes: { name?: string; enabled?: boolean; config?: Record<string, unknown> }) =>
    api.patch<Integration>(`/api/integrations/${id}`, changes),
  test: (id: number) => api.post<{ ok: boolean; message: string }>(`/api/integrations/${id}/test`),
  remove: (id: number) => api.delete(`/api/integrations/${id}`),
  googleStart: (name: string, config: Record<string, unknown>) =>
    api.post<{ integration: Integration; auth_url: string }>('/api/integrations/google/start', { name, config }),
  signIn: (id: number) => api.post<{ auth_url: string }>(`/api/integrations/${id}/sign-in`),
};

/** An integration in the shape of an MCP server, for lists of "your apps" (pickers, mentions, prompts). */
export function asServer(integration: Integration): McpServer {
  return {
    id: -integration.id, slug: integration.slug, name: integration.name, transport: 'http', command: '', args: [], env: {},
    url: '', headers: {}, enabled: integration.enabled, status: integration.enabled ? integration.status : 'stopped', error: null,
    tools: integration.tools, blocked_tools: [], tool_policies: {}, signed_in: false, auth_url: null, health: null,
  } as McpServer;
}

/** Every connected app: MCP servers plus built-in integrations (email, calendar feeds, RSS...). */
export async function listApps(): Promise<McpServer[]> {
  const [servers, integrations] = await Promise.all([
    mcpService.list(),
    integrationService.list().catch(() => [] as Integration[]),
  ]);
  return [...servers, ...integrations.map(asServer)];
}
