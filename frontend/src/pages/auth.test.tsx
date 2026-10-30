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
      Object.assign(status, { hasUsers: true, user: body });  // as the server would
    }
    return new Response(code === 204 ? null : JSON.stringify(body), { status: code, headers: { 'content-type': 'application/json' } });
  }));
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

const app = () => render(
  <MemoryRouter><AuthProvider><AuthGate><p>The app</p><UserMenu /></AuthGate></AuthProvider></MemoryRouter>);
const signedOut = { hasUsers: true, signupsOpen: true, user: null };

/** The first step of signing in: type the email, then Continue. */
async function continueWith(email: string) {
  fireEvent.change(await screen.findByLabelText('Email'), { target: { value: email } });
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
}

test('a first visit creates the owner account from the email step, then opens the app', async () => {
  const calls = serve({ hasUsers: false, signupsOpen: true, user: null },
    { 'POST /api/auth/lookup': [200, { next: 'create' }], 'POST /api/auth/signup': [200, ANA] });
  app();
  expect(await screen.findByRole('heading', { name: 'Welcome to Nexus' })).toBeInTheDocument();
  await continueWith('ana@example.com');
  expect(await screen.findByRole('heading', { name: 'Create your account' })).toBeInTheDocument();
  expect(screen.getByText(/first here/)).toBeInTheDocument();  // this account will own the Nexus
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Ana' } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct horse battery' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create account' }));
  expect(await screen.findByText('The app')).toBeInTheDocument();
  expect(calls.find(c => c.path === '/api/auth/lookup')?.body).toEqual({ email: 'ana@example.com' });
  const signup = calls.find(c => c.path === '/api/auth/signup');
  expect(signup?.body).toEqual({ name: 'Ana', email: 'ana@example.com', password: 'correct horse battery' });
  expect(signup?.credentials).toBe('include');  // so the session cookie is kept and sent
});

test('an email with no account is offered a new one', async () => {
  serve({ ...signedOut }, { 'POST /api/auth/lookup': [200, { next: 'create' }] });
  app();
  await continueWith('bo@example.com');
  expect(await screen.findByRole('heading', { name: 'Create your account' })).toBeInTheDocument();
  expect(screen.getByText(/No account for this email yet/)).toBeInTheDocument();
  expect(screen.getByText('bo@example.com')).toBeInTheDocument();
});

test("a known email asks for its password, and shows the server's message when it's wrong", async () => {
  const calls = serve({ ...signedOut }, { 'POST /api/auth/lookup': [200, { next: 'password' }],
    'POST /api/auth/login': [401, { detail: 'Wrong email or password' }] });
  app();
  await continueWith('ana@example.com');
  expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'not the password' } });
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Wrong email or password');
  expect(calls.find(c => c.path === '/api/auth/login')?.body).toEqual({ email: 'ana@example.com', password: 'not the password' });
  expect(screen.queryByText('The app')).toBeNull();
});

test('Change goes back to the email step and keeps what was typed', async () => {
  serve({ ...signedOut }, { 'POST /api/auth/lookup': [200, { next: 'password' }] });
  app();
  await continueWith('ana@example.com');
  fireEvent.click(await screen.findByRole('button', { name: 'Change email' }));
  expect(await screen.findByRole('heading', { name: 'Welcome to Nexus' })).toBeInTheDocument();
  expect(screen.getByLabelText('Email')).toHaveValue('ana@example.com');
});

test('an account that signs in with Google is sent to Google', async () => {
  serve({ ...signedOut, google: true }, { 'POST /api/auth/lookup': [200, { next: 'google' }] });
  app();
  await continueWith('gabi@example.com');
  expect(await screen.findByRole('heading', { name: 'Sign in with Google' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /Continue with Google/ }).getAttribute('href')).toMatch(/\/api\/auth\/google\/start$/);
});

test('when sign-ups are closed, a new email is told so', async () => {
  serve({ ...signedOut, signupsOpen: false }, { 'POST /api/auth/lookup': [200, { next: 'closed' }] });
  app();
  await continueWith('bo@example.com');
  expect(await screen.findByRole('heading', { name: 'No account for this email' })).toBeInTheDocument();
  expect(screen.getByText(/Sign-ups are closed/)).toBeInTheDocument();
});

/** Straight to the create-account step (a new email). */
async function createStep() {
  const calls = serve({ ...signedOut }, { 'POST /api/auth/lookup': [200, { next: 'create' }] });
  app();
  await continueWith('ana@example.com');
  await screen.findByRole('heading', { name: 'Create your account' });
  return calls;
}

test('a short password is caught before sending', async () => {
  const calls = await createStep();
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: '123456789' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create account' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('At least 10 characters');
  expect(calls.some(c => c.path === '/api/auth/signup')).toBe(false);
});

test('a password with too little variety is caught before sending', async () => {
  const calls = await createStep();
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'ababababab' } });  // 10 chars, 2 distinct
  fireEvent.click(screen.getByRole('button', { name: 'Create account' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('wider mix of characters');
  expect(calls.some(c => c.path === '/api/auth/signup')).toBe(false);
});

test('the password can be shown and hidden, with its requirements shown live', async () => {
  await createStep();
  const pw = screen.getByLabelText('Password') as HTMLInputElement;
  fireEvent.change(pw, { target: { value: 'abc' } });
  expect(pw.type).toBe('password');
  fireEvent.click(screen.getByRole('button', { name: 'Show password' }));
  expect(pw.type).toBe('text');
  fireEvent.click(screen.getByRole('button', { name: 'Hide password' }));
  expect(pw.type).toBe('password');
  expect(screen.getByText('At least 10 characters')).toBeInTheDocument();
  expect(screen.getByText('A mix of different characters')).toBeInTheDocument();
});

test('signed in: the app, your name, and signing out', async () => {
  const calls = serve({ hasUsers: true, signupsOpen: true, user: ANA }, { 'POST /api/auth/logout': [204, null] });
  app();
  expect(await screen.findByText('The app')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Ana/ }));
  fireEvent.click(await screen.findByRole('menuitem', { name: 'Sign out' }));
  await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.path === '/api/auth/logout')).toBe(true));
  expect(await screen.findByRole('heading', { name: 'Welcome to Nexus' })).toBeInTheDocument();
});

test('a 401 from anywhere (an expired session) goes back to signing in', async () => {
  serve({ hasUsers: true, signupsOpen: true, user: ANA });
  app();
  await screen.findByText('The app');
  window.dispatchEvent(new Event('nexus:signed-out'));
  expect(await screen.findByRole('heading', { name: 'Welcome to Nexus' })).toBeInTheDocument();
});

test('resending the verification email starts a cooldown', async () => {
  const calls = serve(
    { hasUsers: true, signupsOpen: true, email: true, user: { id: 2, email: 'bo@example.com', name: 'Bo', isAdmin: false, emailVerified: false } },
    { 'POST /api/auth/resend-verification': [204, null] });
  app();
  fireEvent.click(await screen.findByRole('button', { name: 'Send it again' }));
  await waitFor(() => expect(screen.getByRole('button', { name: /Send it again in \d+s/ })).toBeDisabled());
  expect(calls.some(c => c.path === '/api/auth/resend-verification')).toBe(true);
});

test("the operator's terms and privacy policy are linked when set", async () => {
  serve({ ...signedOut, privacyUrl: 'https://example.com/privacy', termsUrl: 'https://example.com/terms' });
  app();
  expect(await screen.findByRole('link', { name: 'Privacy Policy' })).toHaveAttribute('href', 'https://example.com/privacy');
  expect(screen.getByRole('link', { name: 'Terms' })).toHaveAttribute('href', 'https://example.com/terms');
});

test('without policy links set, none are shown', async () => {
  serve({ ...signedOut });
  app();
  await screen.findByRole('heading', { name: 'Welcome to Nexus' });
  expect(screen.queryByRole('link', { name: 'Privacy Policy' })).toBeNull();
});
