import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { GettingStarted } from './GettingStarted';

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

function serve(servers: unknown[], sessions: unknown[]) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const path = new URL(url).pathname;
    const body = path === '/api/mcp/servers/' ? servers : path === '/api/agent/sessions' ? sessions : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
}

const page = (hasLLM: boolean) => render(<MemoryRouter><GettingStarted hasLLM={hasLLM} /></MemoryRouter>);

test('a new user sees three steps, each linking where to do it', async () => {
  serve([], []);
  page(false);
  const guide = await screen.findByRole('region', { name: 'Getting started' });
  expect(screen.getByRole('link', { name: /Add an AI provider/ })).toHaveAttribute('href', '/settings?tab=ai');
  expect(screen.getByRole('link', { name: /Connect an app/ })).toHaveAttribute('href', '/servers');
  expect(guide).toHaveTextContent('0 of 3 done');
});

test('finished steps are ticked, and the guide can be hidden for good', async () => {
  serve([{ name: 'Notion', enabled: true, status: 'connected' }], []);
  page(true);
  expect(await screen.findByText('2 of 3 done')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Hide getting started' }));
  expect(screen.queryByRole('region', { name: 'Getting started' })).toBeNull();
  expect(localStorage.getItem('nexus.gettingStarted.hidden')).toBe('1');
});

test('nothing is shown once everything is done', async () => {
  serve([{ name: 'Notion', enabled: true, status: 'connected' }], [{ id: 1 }]);
  const { container } = page(true);
  await new Promise(r => setTimeout(r, 50));
  expect(container.textContent).toBe('');
});
