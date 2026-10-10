import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { MarketplacePage } from './MarketplacePage';
import type { MarketCard, SyncStatus } from '../../types/marketplace';

afterEach(() => vi.unstubAllGlobals());

function card(patch: Partial<MarketCard>): MarketCard {
  return {
    name: 'io.x/files', title: 'Files', description: 'Read files', publisher: 'io.x', icon_url: null,
    updated_at: null, installed_server_id: null, status: null,
    verified: false, official: false, ...patch,
  };
}

const idle: SyncStatus = { status: 'idle', count: 2, last_synced_at: '2026-10-09T00:00:00Z', error: null };

function serve(items: MarketCard[], status: SyncStatus = idle, featured: MarketCard[] = []) {
  const calls: { path: string; query: string; method: string }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const parsed = new URL(url);
    calls.push({ path: parsed.pathname, query: parsed.search, method: init.method ?? 'GET' });
    const body = parsed.pathname === '/api/marketplace' ? { items, status }
      : parsed.pathname === '/api/marketplace/featured' ? { items: featured }
      : parsed.pathname === '/api/marketplace/refresh' ? { started: true } : status;
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
  return calls;
}

const page = () => render(<MemoryRouter><MarketplacePage /></MemoryRouter>);

test('lists cards and searches by text', async () => {
  const calls = serve([card({}), card({ name: 'io.x/web', title: 'Web' })]);
  page();
  expect(await screen.findByRole('button', { name: /Files/ })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Web/ })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Search servers'), { target: { value: 'zebra' } });
  await waitFor(() => expect(calls.some(c => c.path === '/api/marketplace' && c.query.includes('q=zebra'))).toBe(true));
});

test('filters to installed', async () => {
  const calls = serve([card({ installed_server_id: 4 })]);
  page();
  expect(await screen.findByText('Installed', { selector: 'span' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('radio', { name: 'Installed' }));
  await waitFor(() => expect(calls.some(c => c.query.includes('kind=installed'))).toBe(true));
});

test('shows the sync error with a Refresh button', async () => {
  const calls = serve([], { status: 'error', count: 0, last_synced_at: null, error: 'timeout' });
  page();
  expect(await screen.findByText("Couldn't reach the MCP Registry: timeout")).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
  await waitFor(() => expect(calls.some(c => c.path === '/api/marketplace/refresh' && c.method === 'POST')).toBe(true));
});

test('only All and Installed views: hosted servers from verified publishers are all there is', async () => {
  serve([card({})]);
  page();
  await screen.findByRole('button', { name: /Files/ });
  expect(screen.getAllByRole('radio').map(r => r.textContent)).toEqual(['All', 'Installed']);
  expect(screen.queryByLabelText('Verified publishers only')).toBeNull();
});

test('installed cards show whether the server works', async () => {
  serve([card({ installed_server_id: 4, status: 'error' })]);
  page();
  expect(await screen.findByLabelText('Status: error')).toBeInTheDocument();
});

test('shows Official and Verified domain badges', async () => {
  serve([
    card({ name: 'com.notion/mcp', title: 'Notion', publisher: 'notion.com', verified: true, official: true }),
    card({ name: 'com.mcparmory/notion', title: 'Armory Notion', publisher: 'mcparmory.com', verified: true }),
    card({ name: 'io.github.awkoy/notion', title: 'Awkoy Notion', publisher: 'github.com/awkoy' }),
  ]);
  page();
  const official = await screen.findByRole('button', { name: /^Notion/ });
  expect(official).toHaveTextContent('Official');
  expect(screen.getByRole('button', { name: /Armory Notion/ })).toHaveTextContent('Verified domain');
  const github = screen.getByRole('button', { name: /Awkoy Notion/ });
  expect(github).not.toHaveTextContent('Verified domain');
  expect(github).not.toHaveTextContent('Official');
});

test('logo comes from the backend and falls back to a letter', async () => {
  serve([card({ name: 'io.x/files', title: 'Files' })]);
  const { container } = page();
  await screen.findByRole('button', { name: /Files/ });
  const img = container.querySelector('img')!;
  expect(img.getAttribute('src')).toContain('/api/marketplace/icon?name=io.x%2Ffiles');
  fireEvent.error(img);
  expect(container.querySelector('img')).toBeNull();
  expect(screen.getByText('F')).toBeInTheDocument();
});

test('Featured shelf on the front page, not while searching', async () => {
  serve([card({})], idle, [card({ name: 'com.notion/mcp', title: 'Notion', official: true, verified: true })]);
  page();
  const shelf = await screen.findByRole('region', { name: 'Featured' });
  expect(shelf).toHaveTextContent('Notion');
  fireEvent.change(screen.getByLabelText('Search servers'), { target: { value: 'files' } });
  await waitFor(() => expect(screen.queryByRole('region', { name: 'Featured' })).toBeNull());
});

test('official only', async () => {
  const calls = serve([card({})]);
  page();
  fireEvent.click(await screen.findByLabelText('Official only'));
  await waitFor(() => expect(calls.some(c => c.query.includes('official=true'))).toBe(true));
  expect(screen.queryByRole('region', { name: 'Featured' })).toBeNull();
});
