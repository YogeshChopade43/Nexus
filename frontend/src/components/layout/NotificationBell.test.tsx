import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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

test('a new reminder pops a browser notification; older ones do not', async () => {
  const shown: { title: string; body?: string }[] = [];
  const FakeNotification = Object.assign(
    function (this: unknown, title: string, options?: { body?: string }) { shown.push({ title, body: options?.body }); },
    { permission: 'granted', requestPermission: vi.fn() },
  );
  vi.stubGlobal('Notification', FakeNotification);
  const old = { id: '3', type: 'reminder', title: 'Old reminder', description: '', timestamp: new Date().toISOString(), unread: false };
  const fresh = { id: '4', type: 'reminder', title: 'Take your medicines', description: '2 tablets', timestamp: new Date().toISOString(), unread: true };
  let items = [old];
  vi.stubGlobal('fetch', vi.fn(async () =>
    new Response(JSON.stringify({ unread: items.length, items }), { status: 200, headers: { 'content-type': 'application/json' } })));

  render(<MemoryRouter><NotificationBell /></MemoryRouter>);
  await screen.findByLabelText('Notifications, 1 unread');
  items = [fresh, old];
  window.dispatchEvent(new Event('focus'));
  await waitFor(() => expect(shown).toEqual([{ title: 'Take your medicines', body: '2 tablets' }]));
});

test('offers to turn on desktop alerts when not yet allowed', async () => {
  const requestPermission = vi.fn(async () => 'granted');
  vi.stubGlobal('Notification', Object.assign(function () {}, { permission: 'default', requestPermission }));
  vi.stubGlobal('fetch', vi.fn(async () =>
    new Response(JSON.stringify({ unread: 0, items: [] }), { status: 200, headers: { 'content-type': 'application/json' } })));
  render(<MemoryRouter><NotificationBell /></MemoryRouter>);
  fireEvent.click(screen.getByLabelText('Notifications'));
  fireEvent.click(screen.getByRole('button', { name: 'Turn on desktop alerts' }));
  expect(requestPermission).toHaveBeenCalled();
});

test('a new reminder also opens an in-app pop-up that stays until dismissed', async () => {
  vi.stubGlobal('Notification', Object.assign(function () {}, { permission: 'denied', requestPermission: vi.fn() }));
  let items: unknown[] = [];
  vi.stubGlobal('fetch', vi.fn(async () =>
    new Response(JSON.stringify({ unread: items.length, items }), { status: 200, headers: { 'content-type': 'application/json' } })));
  render(<MemoryRouter><NotificationBell /></MemoryRouter>);
  await screen.findByLabelText('Notifications');
  items = [{ id: '9', type: 'reminder', title: 'Take your medicines', description: '2 tablets', timestamp: new Date().toISOString(), unread: true }];
  window.dispatchEvent(new Event('focus'));
  const popup = await screen.findByRole('alertdialog', { name: 'Take your medicines' });
  expect(popup).toHaveTextContent('2 tablets');
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
  expect(screen.queryByRole('alertdialog')).toBeNull();
});
