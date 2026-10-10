import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { InstalledServer } from './InstalledServer';
import { InstallForm } from './InstallForm';
import type { McpServer } from '../../types/mcp';
import type { MarketItem } from '../../types/marketplace';

afterEach(() => vi.unstubAllGlobals());

const base: McpServer = {
  id: 7, slug: 'linear', name: 'Linear', transport: 'http', command: '', args: [],
  env: {}, url: 'https://mcp.linear.app/mcp', headers: {}, enabled: true, status: 'connected', error: null, tools: [], blocked_tools: [],
  tool_policies: {}, signed_in: false, auth_url: null, health: null,
};

function serve() {
  const calls: { method: string; path: string; body: unknown }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ method: init.method ?? 'GET', path: new URL(url).pathname, body: init.body ? JSON.parse(init.body as string) : null });
    return new Response(JSON.stringify({ ...base, status: 'connecting' }), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
  return calls;
}

test('a server waiting for sign-in says so plainly', () => {
  serve();
  render(<InstalledServer server={{ ...base, status: 'needs_auth', auth_url: 'https://auth.example/authorize' }} onChanged={() => {}} />);
  const link = screen.getByRole('link', { name: 'Sign in to Linear' });
  expect(link).toHaveAttribute('href', 'https://auth.example/authorize');
});

test('a connecting server says so, and its address is shown', () => {
  serve();
  render(<InstalledServer server={{ ...base, status: 'connecting' }} onChanged={() => {}} />);
  expect(screen.getByText(/^Connecting…/)).toBeInTheDocument();
  expect(screen.getByText('https://mcp.linear.app/mcp')).toBeInTheDocument();
});

test('the custom server form takes a hosted URL only', async () => {
  const calls = serve();
  const { ServerFormModal } = await import('./ServerFormModal');
  render(<ServerFormModal open server={null} onClose={() => {}} onSaved={() => {}} />);
  expect(screen.queryByText('Command')).toBeNull();
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Mine' } });
  fireEvent.change(screen.getByLabelText('Server URL'), { target: { value: 'https://mine.example/mcp' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save & connect' }));
  await waitFor(() => expect(calls.some(c => c.method === 'POST')).toBe(true));
  expect(calls.find(c => c.method === 'POST')!.body).toMatchObject({ name: 'Mine', transport: 'http', url: 'https://mine.example/mcp' });
});

test('import skips local servers and says why', async () => {
  const calls = serve();
  const { ImportModal } = await import('./ImportModal');
  render(<ImportModal open onClose={() => {}} onImported={() => {}} />);
  fireEvent.change(screen.getByLabelText('Config file contents'), { target: { value: JSON.stringify({ mcpServers: {
    local: { command: 'npx', args: ['-y', 'x'] }, linear: { type: 'http', url: 'https://mcp.linear.app/mcp' } } }) } });
  fireEvent.click(screen.getByRole('button', { name: 'Import' }));
  expect(await screen.findByRole('status')).toHaveTextContent(/Skipped local: .*hosted/);
  expect(calls.filter(c => c.method === 'POST').map(c => (c.body as { name: string }).name)).toEqual(['linear']);
});

test('optional install settings are folded away', () => {
  serve();
  const item = {
    name: 'io.x/db', title: 'DB', description: '', publisher: 'x.io', verified: true, official: false,
    icon_url: null, updated_at: null, installed_server_id: null, status: null,
    version: '1', repository_url: null, website_url: null, installed: null,
    launch: { url: 'https://db.example/mcp', headers: {} },
    fields: [
      { key: 'DB_URL', label: 'DB_URL', description: '', required: true, secret: false, default: '' },
      { key: 'DB_TIMEOUT', label: 'DB_TIMEOUT', description: '', required: false, secret: false, default: '' },
    ],
  } as MarketItem;
  const { container } = render(<InstallForm item={item} onInstalled={() => {}} />);
  expect(screen.getByText('Optional settings (1)')).toBeInTheDocument();
  expect(container.querySelector('details')).not.toHaveAttribute('open');
  expect(container.querySelector('details')!.textContent).toContain('DB_TIMEOUT');
  expect(container.querySelector('details')!.textContent).not.toContain('DB_URL');
});
