import { afterEach, expect, test, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Modal } from '../ui/Modal';
import { ImportModal } from './ImportModal';
import { MarketplacePage } from './MarketplacePage';
import type { MarketCard, SyncStatus } from '../../types/marketplace';

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
const idle: SyncStatus = { status: 'idle', count: 1, last_synced_at: null, error: null };

function card(patch: Partial<MarketCard>): MarketCard {
  return {
    name: 'io.x/files', title: 'Files', description: 'Read files', publisher: 'x.io', verified: true, official: false,
    icon_url: null, updated_at: null, installed_server_id: null,
    status: null, ...patch,
  };
}

test('M-4: Escape closes only the top pop-up, and each has its own title', () => {
  const outer = vi.fn();
  const inner = vi.fn();
  render(<Modal open onClose={outer} title="Outer"><Modal open onClose={inner} title="Inner"><p>x</p></Modal></Modal>);
  expect(screen.getByRole('dialog', { name: 'Outer' })).toBeInTheDocument();
  expect(screen.getByRole('dialog', { name: 'Inner' })).toBeInTheDocument();
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(inner).toHaveBeenCalledTimes(1);
  expect(outer).not.toHaveBeenCalled();
});

test('M-5: the import pop-up starts empty each time it opens', () => {
  const { rerender } = render(<ImportModal open onClose={() => {}} onImported={() => {}} />);
  fireEvent.change(screen.getByLabelText('Config file contents'), { target: { value: '{"mcpServers": {}}' } });
  rerender(<ImportModal open={false} onClose={() => {}} onImported={() => {}} />);
  rerender(<ImportModal open onClose={() => {}} onImported={() => {}} />);
  expect(screen.getByLabelText('Config file contents')).toHaveValue('');
});

test('M-7: a slow older search result never replaces a newer one', async () => {
  const pending: Record<string, (r: Response) => void> = {};
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const parsed = new URL(url);
    if (parsed.pathname.startsWith('/api/integrations')) return Promise.resolve(json([]));
    if (parsed.pathname !== '/api/marketplace') return Promise.resolve(json({ items: [] }));
    return new Promise<Response>(resolve => { pending[parsed.searchParams.get('q') ?? ''] = resolve; });
  }));
  render(<MemoryRouter><MarketplacePage /></MemoryRouter>);
  await waitFor(() => expect(pending['']).toBeDefined());
  fireEvent.change(screen.getByLabelText('Search servers'), { target: { value: 'new' } });
  await waitFor(() => expect(pending['new']).toBeDefined());
  await act(async () => { pending['new'](json({ items: [card({ title: 'Newer' })], status: idle })); });
  await act(async () => { pending[''](json({ items: [card({ title: 'Older' })], status: idle })); });
  expect(screen.getByRole('button', { name: /Newer/ })).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Older/ })).toBeNull();
});

test('M-8: listings appear while the first sync is still running', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let count = 0;
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const path = new URL(url).pathname;
    if (path.startsWith('/api/integrations')) return json([]);  // no built-in integrations connected
    if (path === '/api/marketplace/status') return json({ status: 'syncing', count: 5, last_synced_at: null, error: null });
    if (path === '/api/marketplace') {
      count += 1;
      return json({ items: count > 1 ? [card({ title: 'Arrived' })] : [],
                    status: { status: 'syncing', count: 0, last_synced_at: null, error: null } });
    }
    return json({ items: [] });
  }));
  render(<MemoryRouter><MarketplacePage /></MemoryRouter>);
  await screen.findByText(/Downloading the MCP Registry/);
  await act(async () => { vi.advanceTimersByTime(3100); });
  expect(await screen.findByRole('button', { name: /Arrived/ })).toBeInTheDocument();
});

test('M-3: changing a server in its panel updates its card without reloading the grid', async () => {
  const calls: string[] = [];
  let installed = false;
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const path = new URL(url).pathname;
    if (path.startsWith('/api/integrations')) return json([]);  // no built-in integrations connected
    calls.push(`${init.method ?? 'GET'} ${path}`);
    if (path === '/api/marketplace') return json({ items: [card({})], status: idle });
    if (path === '/api/marketplace/item') {
      return json({ ...card(installed ? { installed_server_id: 9, status: 'connected' } : {}), version: '1', repository_url: null,
        website_url: null, fields: [], launch: { url: 'https://x/mcp', headers: {} },
        installed: installed ? { id: 9, slug: 'files', name: 'Files', transport: 'http', command: '', args: [], env: {},
          url: 'https://x/mcp', headers: {}, enabled: true, status: 'connected', error: null, tools: [], blocked_tools: [],
          tool_policies: {}, signed_in: false, auth_url: null, health: null } : null });
    }
    if (path === '/api/marketplace/install') {
      installed = true;
      return json({ id: 9, status: 'connected' });
    }
    return json({ items: [] });
  }));
  render(<MemoryRouter><MarketplacePage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: /Files/ }));
  fireEvent.click(await screen.findByRole('button', { name: 'Install' }));
  await screen.findByRole('button', { name: 'Remove server' });
  fireEvent.click(screen.getByRole('button', { name: 'Close modal' }));
  await waitFor(() => expect(screen.getByRole('button', { name: /Files/ })).toHaveTextContent('Installed'));
  expect(calls.filter(c => c === 'GET /api/marketplace')).toHaveLength(1);
});
