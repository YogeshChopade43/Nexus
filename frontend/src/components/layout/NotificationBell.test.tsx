import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { NotificationBell } from './NotificationBell';

afterEach(() => vi.unstubAllGlobals());

test('shows the unread count and marks it read when opened', async () => {
  const calls: { path: string; method: string }[] = [];
  const routes: Record<string, unknown> = {
    '/api/activity/notifications': {
      unread: 2,
      items: [{ id: '1', type: 'workflow_failed', title: "Workflow 'x' failed", description: 'boom', timestamp: new Date().toISOString(), unread: true }],
    },
    '/api/activity/notifications/read': { unread: 0 },
  };
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const path = new URL(url).pathname;
    calls.push({ path, method: init.method ?? 'GET' });
    return new Response(JSON.stringify(routes[path] ?? {}), { status: 200, headers: { 'content-type': 'application/json' } });
  }));

  render(<MemoryRouter><NotificationBell /></MemoryRouter>);
  fireEvent.click(await screen.findByLabelText('Notifications, 2 unread'));
  expect(screen.getByText("Workflow 'x' failed")).toBeInTheDocument();
  await screen.findByLabelText('Notifications');
  expect(calls.some(c => c.path === '/api/activity/notifications/read' && c.method === 'POST')).toBe(true);
});
