// Self-check for MCP config import. Run: npx tsx src/components/servers/catalog.check.ts
import assert from 'node:assert/strict';
import { parseMcpConfig } from './catalog';

// Claude Desktop / .mcp.json
const desktop = parseMcpConfig(JSON.stringify({
  mcpServers: {
    notion: { command: 'npx', args: ['-y', '@notionhq/notion-mcp-server'], env: { NOTION_TOKEN: 'x' } },
    linear: { type: 'http', url: 'https://mcp.linear.app/mcp', headers: { 'X-Key': 1 } },
    old: { type: 'sse', url: 'https://example.com/sse' },
    broken: {},
  },
}));
assert.deepEqual(desktop.servers, [
  { name: 'notion', transport: 'stdio', command: 'npx', args: ['-y', '@notionhq/notion-mcp-server'], env: { NOTION_TOKEN: 'x' } },
  { name: 'linear', transport: 'http', url: 'https://mcp.linear.app/mcp', headers: { 'X-Key': '1' } },
]);
assert.equal(desktop.skipped.length, 2);

// VS Code and ~/.claude.json project entries; the first server with a name wins
const code = parseMcpConfig(JSON.stringify({
  servers: { time: { command: 'uvx', args: ['mcp-server-time'] } },
  projects: { 'D:/a': { mcpServers: { time: { command: 'other' }, git: { command: 'uvx' } } } },
}));
assert.deepEqual(code.servers.map(s => [s.name, s.command]), [['time', 'uvx'], ['git', 'uvx']]);

assert.throws(() => parseMcpConfig('{"other": 1}'), /No servers found/);
assert.throws(() => parseMcpConfig('not json'));
console.log('catalog checks passed');
