import type { McpServerInput } from '../../types/mcp';

export interface CatalogEntry {
  description: string;
  /** Shown in the form: what still needs filling in. */
  note?: string;
  server: McpServerInput;
}

/** Shortcuts that prefill the Add server form. Any other MCP server works the same way. */
export const CATALOG: CatalogEntry[] = [
  {
    description: 'Hosted by Notion. Sign in with your Notion account; no token needed.',
    server: { name: 'Notion', transport: 'http', url: 'https://mcp.notion.com/mcp' },
  },
  {
    description: 'Hosted by Linear. Sign in with your Linear account.',
    server: { name: 'Linear', transport: 'http', url: 'https://mcp.linear.app/mcp' },
  },
  {
    description: 'Hosted by Sentry. Sign in with your Sentry account.',
    server: { name: 'Sentry', transport: 'http', url: 'https://mcp.sentry.dev/mcp' },
  },
  {
    description: 'Hosted by GitHub, using a personal access token.',
    note: 'Replace <token> with a GitHub personal access token.',
    server: { name: 'GitHub', transport: 'http', url: 'https://api.githubcopilot.com/mcp/', headers: { Authorization: 'Bearer <token>' } },
  },
  {
    description: 'Notion run on this computer with an integration token.',
    note: 'Set NOTION_TOKEN to an internal integration secret (ntn_…). Needs Node.js.',
    server: { name: 'Notion (local)', transport: 'stdio', command: 'npx', args: ['-y', '@notionhq/notion-mcp-server'], env: { NOTION_TOKEN: '' } },
  },
  {
    description: 'Read and write files in one folder on this computer.',
    note: 'Replace <folder> with the folder to allow. Needs Node.js.',
    server: { name: 'Files', transport: 'stdio', command: 'npx', args: ['-y', '@modelcontextprotocol/server-filesystem', '<folder>'] },
  },
  {
    description: 'Fetch web pages and turn them into text.',
    note: 'Needs uv (uvx).',
    server: { name: 'Fetch', transport: 'stdio', command: 'uvx', args: ['mcp-server-fetch'] },
  },
  {
    description: 'Read history and diffs of a local git repository.',
    note: 'Replace <path> with the repository folder. Needs uv (uvx).',
    server: { name: 'Git', transport: 'stdio', command: 'uvx', args: ['mcp-server-git', '--repository', '<path>'] },
  },
  {
    description: 'Current time and time-zone conversion.',
    note: 'Needs uv (uvx).',
    server: { name: 'Time', transport: 'stdio', command: 'uvx', args: ['mcp-server-time'] },
  },
  {
    description: 'A small knowledge graph the agent can remember things in.',
    note: 'Needs Node.js.',
    server: { name: 'Memory', transport: 'stdio', command: 'npx', args: ['-y', '@modelcontextprotocol/server-memory'] },
  },
  {
    description: 'Drive a real browser: open pages, click, fill forms.',
    note: 'Needs Node.js.',
    server: { name: 'Browser', transport: 'stdio', command: 'npx', args: ['@playwright/mcp@latest'] },
  },
];

type RawServer = { command?: unknown; args?: unknown; env?: unknown; url?: unknown; headers?: unknown; type?: unknown };

const strings = (value: unknown): Record<string, string> =>
  value && typeof value === 'object'
    ? Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, String(v)]))
    : {};

/**
 * Servers from an MCP config file: Claude Desktop / Cursor / `.mcp.json` (`mcpServers`),
 * VS Code (`servers`), or Claude Code's `~/.claude.json` (also per-project `mcpServers`).
 */
export function parseMcpConfig(text: string): { servers: McpServerInput[]; skipped: string[] } {
  const json = JSON.parse(text) as Record<string, unknown>;
  const groups: unknown[] = [json.mcpServers, json.servers];
  if (json.projects && typeof json.projects === 'object') {
    for (const project of Object.values(json.projects as Record<string, { mcpServers?: unknown }>)) groups.push(project?.mcpServers);
  }
  const servers: McpServerInput[] = [];
  const skipped: string[] = [];
  const seen = new Set<string>();
  for (const group of groups) {
    if (!group || typeof group !== 'object') continue;
    for (const [name, raw] of Object.entries(group as Record<string, RawServer>)) {
      if (seen.has(name)) continue;
      seen.add(name);
      if (typeof raw?.command === 'string' && raw.command) {
        servers.push({
          name, transport: 'stdio', command: raw.command,
          args: Array.isArray(raw.args) ? raw.args.map(String) : [], env: strings(raw.env),
        });
      } else if (typeof raw?.url === 'string' && raw.url) {
        if (raw.type === 'sse') skipped.push(`${name} (uses the older SSE transport, which Nexus doesn't support)`);
        else servers.push({ name, transport: 'http', url: raw.url, headers: strings(raw.headers) });
      } else {
        skipped.push(`${name} (no command or url)`);
      }
    }
  }
  if (servers.length === 0 && skipped.length === 0) throw new Error('No servers found. Expected an "mcpServers" or "servers" object.');
  return { servers, skipped };
}
