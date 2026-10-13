import { afterEach, expect, test, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { SystemStatus, type Status } from './SystemStatus';

afterEach(() => vi.unstubAllGlobals());

function serve(status: Status) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(status), { status: 200, headers: { 'content-type': 'application/json' } })));
}

const healthy: Status = {
  scheduler: { running: true, jobs: 3 },
  apps: [{ name: 'GitHub', kind: 'app', status: 'connected', error: null }],
  last_failure: null,
  telegram_linked: true,
};

test('all good says so', async () => {
  serve(healthy);
  render(<MemoryRouter><SystemStatus /></MemoryRouter>);
  expect(await screen.findByText('Everything is working')).toBeInTheDocument();
  expect(screen.getByText(/3 scheduled/)).toBeInTheDocument();
});

test('problems are listed first, each with what to do', async () => {
  serve({ ...healthy, telegram_linked: false,
    apps: [...healthy.apps, { name: 'Notion', kind: 'app', status: 'error', error: 'Token expired' },
      { name: 'Google', kind: 'google', status: 'needs_auth', error: null }],
    last_failure: { workflow_id: 4, name: 'Digest', started_at: '2026-10-12T09:00:00Z', error: 'Timed out' } });
  render(<MemoryRouter><SystemStatus /></MemoryRouter>);
  expect(await screen.findByText('3 things need attention')).toBeInTheDocument();
  expect(screen.getByText(/Notion/)).toBeInTheDocument();
  expect(screen.getByText(/Token expired/)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /Digest/ })).toHaveAttribute('href', '/workflows?open=4');
  expect(screen.getByRole('link', { name: /Link Telegram/ })).toHaveAttribute('href', '/servers');
});
