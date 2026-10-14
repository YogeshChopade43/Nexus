import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../hooks/useAuth';
import { AuthGate } from './AuthPage';
import { UserMenu } from '../components/layout/UserMenu';

const ANA = { id: 1, email: 'ana@example.com', name: 'Ana', isAdmin: true };

function serve(status: Record<string, unknown>, replies: Record<string, [number, unknown]> = {}) {
  const calls: { method: string; path: string; body: unknown; credentials?: string }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET';
    const path = new URL(url).pathname;
    calls.push({ method, path, body: init.body ? JSON.parse(String(init.body)) : null, credentials: init.credentials });
    const [code, body] = path === '/api/auth/status' ? [200, status] : replies[`${method} ${path}`] ?? [200, {}];
    if (code === 200 && (path === '/api/auth/signup' || path === '/api/auth/login')) {
      Object.assign(status, { hasUsers: true, signupsOpen: false, user: body });  // as the server would
    }
    return new Response(code === 204 ? null : JSON.stringify(body), { status: code, headers: { 'content-type': 'application/json' } });
  }));
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

const app = () => render(
  <MemoryRouter><AuthProvider><AuthGate><p>The app</p><UserMenu /></AuthGate></AuthProvider></MemoryRouter>);

test('a first visit asks to create the owner account, then opens the app', async () => {
  const calls = serve({ hasUsers: false, signupsOpen: true, user: null }, { 'POST /api/auth/signup': [200, ANA] });
  app();
  expect(await screen.findByRole('heading', { name: 'Create your Nexus account' })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Ana' } });
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ana@example.com' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct horse battery' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create account' }));
  expect(await screen.findByText('The app')).toBeInTheDocument();
  const signup = calls.find(c => c.path === '/api/auth/signup');
  expect(signup?.body).toEqual({ name: 'Ana', email: 'ana@example.com', password: 'correct horse battery' });
  expect(signup?.credentials).toBe('include');  // so the session cookie is kept and sent
});

test("signing in shows the server's message when it fails, and offers no sign-up while closed", async () => {
  serve({ hasUsers: true, signupsOpen: false, user: null }, { 'POST /api/auth/login': [401, { detail: 'Wrong email or password' }] });
  app();
  expect(await screen.findByRole('heading', { name: 'Sign in to Nexus' })).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: /Create an account/ })).toBeNull();
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ana@example.com' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'not the password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Wrong email or password');
  expect(screen.queryByText('The app')).toBeNull();
});

test('a short password is caught before sending', async () => {
  const calls = serve({ hasUsers: false, signupsOpen: true, user: null });
  app();
  await screen.findByRole('heading', { name: 'Create your Nexus account' });
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ana@example.com' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: '123456789' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create account' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('At least 10 characters');
  expect(calls.some(c => c.path === '/api/auth/signup')).toBe(false);
});

test('signed in: the app, your name, and signing out', async () => {
  const calls = serve({ hasUsers: true, signupsOpen: false, user: ANA }, { 'POST /api/auth/logout': [204, null] });
  app();
  expect(await screen.findByText('The app')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Ana/ }));
  fireEvent.click(await screen.findByRole('menuitem', { name: 'Sign out' }));
  await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.path === '/api/auth/logout')).toBe(true));
  expect(await screen.findByRole('heading', { name: 'Sign in to Nexus' })).toBeInTheDocument();
});

test('a 401 from anywhere (an expired session) goes back to signing in', async () => {
  serve({ hasUsers: true, signupsOpen: false, user: ANA });
  app();
  await screen.findByText('The app');
  window.dispatchEvent(new Event('nexus:signed-out'));
  expect(await screen.findByRole('heading', { name: 'Sign in to Nexus' })).toBeInTheDocument();
});
