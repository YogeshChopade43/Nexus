import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { AuthProvider } from '../../hooks/useAuth';
import { AdminSettings } from './AdminSettings';

const OWNER = { id: 1, email: 'owner@example.com', name: 'Owner', isAdmin: true, emailVerified: true, hasPassword: true, google: false };
const BO = { id: 2, email: 'bo@example.com', name: 'Bo', isAdmin: false, emailVerified: true, hasPassword: true, google: false,
  disabled: false, createdAt: '2026-10-01T10:00:00Z', tokens30d: 12500, storageBytes: 3 * 1048576 };

function serve() {
  const calls: { method: string; path: string; body: unknown }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET';
    const path = new URL(url).pathname;
    const body = init.body ? JSON.parse(String(init.body)) : null;
    calls.push({ method, path, body });
    const replies: Record<string, unknown> = {
      'GET /api/auth/status': { hasUsers: true, signupsOpen: false, user: OWNER },
      'GET /api/admin/users': [{ ...OWNER, disabled: false, createdAt: '2026-09-01T10:00:00Z', tokens30d: 0, storageBytes: 0 }, BO],
      'GET /api/admin/instance': { signups: null, storageLimitMb: 1024 },
      'GET /api/admin/deployment': [
        { id: 'database', title: 'Database', ok: true, detail: 'PostgreSQL.' },
        { id: 'https', title: 'HTTPS', ok: false, detail: 'Put Nexus behind a TLS proxy.' },
      ],
      'PATCH /api/admin/users/2': { ...BO, ...body },
      'PATCH /api/admin/instance': { signups: null, storageLimitMb: 1024, ...body },
    };
    return new Response(JSON.stringify(replies[`${method} ${path}`] ?? {}), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

const show = () => render(<AuthProvider><AdminSettings /></AuthProvider>);

test('the checklist says what is ready and what still needs doing', async () => {
  serve();
  show();
  const https = (await screen.findByText('HTTPS')).closest('li')!;
  expect(within(https).getByText('Needs attention')).toBeInTheDocument();
  expect(within(https).getByText('Put Nexus behind a TLS proxy.')).toBeInTheDocument();
  expect(within(screen.getByText('Database').closest('li')!).getByText('Ready')).toBeInTheDocument();
});

test('accounts show their usage, and someone can be disabled (never yourself)', async () => {
  const calls = serve();
  show();
  const bo = (await screen.findByText('bo@example.com')).closest('tr')!;
  expect(within(bo).getByText('3.0 MB')).toBeInTheDocument();
  expect(within(bo).getByText('12,500')).toBeInTheDocument();
  const owner = screen.getByText('owner@example.com').closest('tr')!;
  expect(within(owner).queryByRole('button', { name: /Disable/ })).toBeNull();
  fireEvent.click(within(bo).getByRole('button', { name: 'Disable bo@example.com' }));
  await waitFor(() => expect(calls.find(c => c.method === 'PATCH')?.body).toEqual({ disabled: true }));
  expect(await within(bo).findByText('Disabled')).toBeInTheDocument();
});

test('sign-ups and the storage limit are saved for the whole instance', async () => {
  const calls = serve();
  show();
  fireEvent.change(await screen.findByLabelText('Sign-ups'), { target: { value: 'open' } });
  fireEvent.change(screen.getByLabelText('Storage per person (MB)'), { target: { value: '500' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(calls.find(c => c.method === 'PATCH' && c.path === '/api/admin/instance')?.body)
    .toEqual({ signups: 'open', storageLimitMb: 500 }));
});
