import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ListingPanel } from './ListingPanel';
import type { MarketCard, MarketItem } from '../../types/marketplace';
import type { McpServer } from '../../types/mcp';

afterEach(() => vi.unstubAllGlobals());

const card: MarketCard = {
  name: 'io.x/hosted', title: 'Hosted Thing', description: 'Invoices', publisher: 'io.x', icon_url: null,
  updated_at: null, installed_server_id: null, status: null,
  verified: true, official: false,
};

function item(patch: Partial<MarketItem>): MarketItem {
  return {
    ...card, version: '1', repository_url: 'https://github.com/x/hosted', website_url: null, installed: null,
    launch: { url: 'https://h/mcp', headers: { Authorization: 'Bearer {api_key}' } },
    fields: [
      { key: 'api_key', label: 'api_key', description: 'Your key', required: true, secret: true, default: '' },
      { key: 'region', label: 'region', description: '', required: false, secret: false, default: 'us' },
    ],
    ...patch,
  };
}

const server: McpServer = {
  id: 4, slug: 'hosted_thing', name: 'Hosted Thing', transport: 'http', command: '', args: [], env: {}, url: 'https://h/mcp',
  headers: { Authorization: '***' }, enabled: true, status: 'connected', error: null, tools: [], blocked_tools: [],
  tool_policies: {}, signed_in: false, auth_url: null, health: null,
};

/** fetch stub: "METHOD /path" -> list of [status, body] replies (the last one repeats). */
function serve(routes: Record<string, [number, unknown][]>) {
  const calls: { key: string; body: unknown }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const key = `${init.method ?? 'GET'} ${new URL(url).pathname}`;
    calls.push({ key, body: init.body ? JSON.parse(init.body as string) : null });
    const queue = routes[key] ?? [[200, {}]];
    const [status, body] = queue.length > 1 ? queue.shift()! : queue[0];
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
  }));
  return calls;
}

test('install form masks secrets and requires fields', async () => {
  const calls = serve({
    'GET /api/marketplace/item': [[200, item({})]],
    'POST /api/marketplace/install': [[422, { detail: 'api_key is required' }], [200, server]],
  });
  render(<ListingPanel card={card} onClose={() => {}} onChanged={() => {}} />);
  const key = await screen.findByLabelText(/api_key/);
  expect(key).toHaveAttribute('type', 'password');
  expect(screen.getByLabelText(/region/)).toHaveValue('us');
  expect(screen.getByText('io.x/hosted')).toBeInTheDocument();  // the real registry ID, beside the readable title
  fireEvent.click(screen.getByRole('button', { name: 'Install' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('api_key is required');
  fireEvent.change(key, { target: { value: 'k' } });
  fireEvent.click(screen.getByRole('button', { name: 'Install' }));
  await waitFor(() => expect(calls.filter(c => c.key === 'POST /api/marketplace/install')).toHaveLength(2));
  expect(calls.filter(c => c.key === 'POST /api/marketplace/install')[1].body)
    .toEqual({ name: 'io.x/hosted', values: { api_key: 'k', region: 'us' } });
});

test('installed item shows management controls', async () => {
  serve({ 'GET /api/marketplace/item': [[200, item({ installed: server, installed_server_id: 4 })]] });
  render(<ListingPanel card={{ ...card, installed_server_id: 4 }} onClose={() => {}} onChanged={() => {}} />);
  expect(await screen.findByRole('button', { name: 'Reconnect' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Remove server' })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Install' })).toBeNull();
});

test('shows where installing connects', async () => {
  serve({ 'GET /api/marketplace/item': [[200, item({})]] });
  render(<ListingPanel card={card} onClose={() => {}} onChanged={() => {}} />);
  const preview = await screen.findByLabelText('Where Nexus will connect');
  expect(preview).toHaveTextContent('https://h/mcp');
  expect(preview).toHaveTextContent('Authorization: Bearer {api_key}');
});
