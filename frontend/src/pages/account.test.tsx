import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../hooks/useAuth';
import { AuthGate } from './AuthPage';
import { AccountSettings } from '../components/settings/AccountSettings';

const ANA = { id: 1, email: 'ana@example.com', name: 'Ana', isAdmin: false, emailVerified: true, hasPassword: true, google: false };

function serve(status: Record<string, unknown>, replies: Record<string, [number, unknown]> = {}) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET';
    const path = new URL(url).pathname;
    calls.push({ method, path, body: init.body ? JSON.parse(String(init.body)) : null });
    const [code, body] = path === '/api/auth/status' ? [200, status] : replies[`${method} ${path}`] ?? [200, {}];
    if (code === 200 && ['/api/auth/reset-password', '/api/auth/login'].includes(path)) Object.assign(status, { user: body });
    return new Response(code === 204 ? null : JSON.stringify(body), { status: code, headers: { 'content-type': 'application/json' } });
  }));
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

const at = (path: string) => render(
  <MemoryRouter initialEntries={[path]}><AuthProvider><AuthGate><p>The app</p></AuthGate></AuthProvider></MemoryRouter>);
const signedOut = { hasUsers: true, signupsOpen: true, user: null, google: true, email: true };

test('sign-in offers Google and a forgotten password, and shows why a Google sign-in failed', async () => {
  serve({ ...signedOut });
  at('/login?error=Sign-ups%20are%20closed');
  const google = await screen.findByRole('link', { name: /Continue with Google/ });
  expect(google.getAttribute('href')).toMatch(/\/api\/auth\/google\/start$/);
  expect(screen.getByRole('alert')).toHaveTextContent('Sign-ups are closed');
  expect(screen.getByRole('link', { name: 'Forgot password?' })).toHaveAttribute('href', '/forgot-password');
});

test('without Google keys or email there is neither button', async () => {
  serve({ ...signedOut, google: false, email: false });
  at('/login');
  await screen.findByRole('heading', { name: 'Sign in to Nexus' });
  expect(screen.queryByRole('link', { name: /Continue with Google/ })).toBeNull();
  expect(screen.queryByRole('link', { name: 'Forgot password?' })).toBeNull();
});

test('forgot password sends a link, and says the same whatever the email', async () => {
  const calls = serve({ ...signedOut }, { 'POST /api/auth/forgot-password': [204, null] });
  at('/forgot-password');
  fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'ana@example.com' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send reset link' }));
  expect(await screen.findByRole('status')).toHaveTextContent(/If there's an account for ana@example.com/);
  expect(calls.find(c => c.path === '/api/auth/forgot-password')?.body).toEqual({ email: 'ana@example.com' });
});

test('the reset link sets a new password and opens the app', async () => {
  const calls = serve({ ...signedOut }, { 'POST /api/auth/reset-password': [200, ANA] });
  at('/reset-password?token=tok-1');
  fireEvent.change(await screen.findByLabelText('New password'), { target: { value: 'a brand new password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Set new password' }));
  expect(await screen.findByText('The app')).toBeInTheDocument();
  expect(calls.find(c => c.path === '/api/auth/reset-password')?.body).toEqual({ token: 'tok-1', password: 'a brand new password' });
});

test('the verify link confirms the email', async () => {
  const calls = serve({ ...signedOut, user: { ...ANA, emailVerified: false } }, { 'POST /api/auth/verify-email': [200, ANA] });
  at('/verify-email?token=tok-2');
  expect(await screen.findByText('The app')).toBeInTheDocument();
  expect(calls.find(c => c.path === '/api/auth/verify-email')?.body).toEqual({ token: 'tok-2' });
});

test('an account that still has to verify sees "check your email" and can resend', async () => {
  const calls = serve({ ...signedOut, user: { ...ANA, emailVerified: false } }, { 'POST /api/auth/resend-verification': [204, null] });
  at('/');
  expect(await screen.findByRole('heading', { name: 'Check your email' })).toBeInTheDocument();
  expect(screen.queryByText('The app')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Send it again' }));
  await waitFor(() => expect(calls.some(c => c.path === '/api/auth/resend-verification')).toBe(true));
});

const account = (replies: Record<string, [number, unknown]> = {}) => {
  const calls = serve({ ...signedOut, user: ANA }, {
    'GET /api/auth/sessions': [200, [{ id: 'a1', createdAt: '2026-10-14T08:00:00Z', userAgent: 'Chrome on Windows', current: true },
      { id: 'b2', createdAt: '2026-10-13T08:00:00Z', userAgent: 'Safari on iPhone', current: false }]],
    ...replies,
  });
  render(<MemoryRouter><AuthProvider><AccountSettings /></AuthProvider></MemoryRouter>);
  return calls;
};

test('account: rename, and change the password (the wrong current one is refused)', async () => {
  const calls = account({ 'PATCH /api/auth/me': [200, { ...ANA, name: 'Ana Lee' }],
    'POST /api/auth/change-password': [403, { detail: "Your current password isn't right" }] });
  fireEvent.change(await screen.findByLabelText('Name'), { target: { value: 'Ana Lee' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save name' }));
  await waitFor(() => expect(calls.find(c => c.method === 'PATCH')?.body).toEqual({ name: 'Ana Lee' }));
  fireEvent.change(screen.getByLabelText('Current password'), { target: { value: 'wrong one here' } });
  fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'a brand new password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Change password' }));
  expect(await screen.findByRole('alert')).toHaveTextContent("Your current password isn't right");
});

test('account: sessions on other devices can be signed out', async () => {
  const calls = account({ 'DELETE /api/auth/sessions/b2': [204, null] });
  expect(await screen.findByText('Safari on iPhone')).toBeInTheDocument();
  expect(screen.getByText('This device')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Sign out Safari on iPhone' }));
  await waitFor(() => expect(calls.some(c => c.method === 'DELETE' && c.path === '/api/auth/sessions/b2')).toBe(true));
});

test('account: export is a download, and deleting needs the password', async () => {
  const calls = account({ 'DELETE /api/auth/me': [204, null] });
  expect((await screen.findByRole('link', { name: /Export my data/ })).getAttribute('href')).toMatch(/\/api\/auth\/export$/);
  fireEvent.click(screen.getByRole('button', { name: 'Delete my account…' }));
  const confirm = screen.getByRole('button', { name: 'Delete everything' });
  expect(confirm).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Your password'), { target: { value: 'test password 123' } });
  fireEvent.click(confirm);
  await waitFor(() => expect(calls.find(c => c.method === 'DELETE' && c.path === '/api/auth/me')?.body).toEqual({ password: 'test password 123' }));
});
