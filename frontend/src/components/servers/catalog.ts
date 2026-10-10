import type { McpServerInput } from '../../types/mcp';

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
