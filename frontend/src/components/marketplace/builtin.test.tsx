import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BuiltInSection, IntegrationModal } from './BuiltIn';
import type { Integration, IntegrationKind } from '../../services/integrations';

afterEach(() => vi.unstubAllGlobals());

const email: IntegrationKind = {
  id: 'email', title: 'Email (IMAP/SMTP)', description: 'Read and send email', icon: 'Mail', fields: [
    { name: 'address', label: 'Email address', type: 'email', required: true, default: null, help: '', advanced: false },
    { name: 'password', label: 'App password', type: 'password', required: true, default: null, help: 'Use an app password', advanced: false },
    { name: 'imap_host', label: 'IMAP server', type: 'text', required: false, default: null, help: '', advanced: true },
  ],
};

const connected: Integration = {
  id: 3, kind: 'email', name: 'Work email', slug: 'work_email', enabled: true, created_at: '', settings: { address: 'me@x.com' },
  status: 'connected', message: 'Signed in as me@x.com', tools: [
    { name: 'work_email__search_emails', remote_name: 'search_emails', description: '', policy: 'allow' },
    { name: 'work_email__send_email', remote_name: 'send_email', description: '', policy: 'ask' },
  ],
};

function serve(responses: Record<string, [number, unknown]>) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET';
    const path = new URL(url).pathname;
    calls.push({ method, path, body: init.body ? JSON.parse(init.body as string) : null });
    const [status, body] = responses[`${method} ${path}`] ?? [200, {}];
    return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
  }));
  return calls;
}

test('built-in apps are listed with how many are connected', () => {
  const onOpen = vi.fn();
  render(<BuiltInSection kinds={[email]} integrations={[connected]} onOpen={onOpen} />);
  fireEvent.click(screen.getByRole('button', { name: /Email \(IMAP\/SMTP\)/ }));
  expect(onOpen).toHaveBeenCalledWith(email);
  expect(screen.getByText('1 connected')).toBeInTheDocument();
});

test('connecting sends the form and shows what the check found; errors are shown in place', async () => {
  const calls = serve({ 'POST /api/integrations': [422, { detail: 'The email server refused the sign-in' }] });
  const onChanged = vi.fn();
  render(<IntegrationModal kind={email} integrations={[]} onClose={() => {}} onChanged={onChanged} />);
  fireEvent.change(screen.getByLabelText(/Email address/), { target: { value: 'me@x.com' } });
  expect(screen.getByLabelText(/App password/)).toHaveAttribute('type', 'password');
  fireEvent.change(screen.getByLabelText(/App password/), { target: { value: 'secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('refused the sign-in');
  expect(calls.at(-1)).toMatchObject({ method: 'POST', body: { kind: 'email', name: 'Email', config: { address: 'me@x.com', password: 'secret' } } });
  expect(onChanged).not.toHaveBeenCalled();
});

test('a connected account can be tested and removed', async () => {
  const calls = serve({ 'POST /api/integrations/3/test': [200, { ok: true, message: 'Works. Signed in as me@x.com' }],
    'DELETE /api/integrations/3': [204, null] });
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  const onChanged = vi.fn();
  render(<IntegrationModal kind={email} integrations={[connected]} onClose={() => {}} onChanged={onChanged} />);
  expect(screen.getByText('Work email')).toBeInTheDocument();
  expect(screen.getByText(/2 tools/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Test Work email' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Works. Signed in as me@x.com');
  fireEvent.click(screen.getByRole('button', { name: 'Remove Work email' }));
  await waitFor(() => expect(onChanged).toHaveBeenCalled());
  expect(calls.some(c => c.method === 'DELETE' && c.path === '/api/integrations/3')).toBe(true);
});

const googleKind: IntegrationKind = {
  id: 'google', title: 'Google (Gmail, Calendar, Drive)', description: '', icon: 'Google',
  redirect_uri: 'http://localhost:8000/api/integrations/google/callback', fields: [
    { name: 'client_id', label: 'OAuth client ID', type: 'text', required: true, default: null, help: '', advanced: false },
    { name: 'client_secret', label: 'OAuth client secret', type: 'password', required: true, default: null, help: '', advanced: false },
  ],
};

test('Google shows the redirect address to register, then signs in in a new tab', async () => {
  const calls = serve({ 'POST /api/integrations/google/start': [200, { auth_url: 'https://accounts.google.com/o/oauth2/v2/auth?x=1',
    integration: { ...connected, id: 8, kind: 'google', name: 'Google', status: 'needs_auth', tools: [] } }],
    'GET /api/integrations': [200, []] });
  const open = vi.spyOn(window, 'open').mockReturnValue(null);
  render(<IntegrationModal kind={googleKind} integrations={[]} onClose={() => {}} onChanged={() => {}} />);
  expect(screen.getByText('http://localhost:8000/api/integrations/google/callback')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/OAuth client ID/), { target: { value: 'cid' } });
  fireEvent.change(screen.getByLabelText(/OAuth client secret/), { target: { value: 'shh' } });
  fireEvent.click(screen.getByRole('button', { name: 'Sign in with Google' }));
  await waitFor(() => expect(open).toHaveBeenCalledWith('https://accounts.google.com/o/oauth2/v2/auth?x=1', '_blank', 'noopener'));
  expect(calls.find(c => c.path === '/api/integrations/google/start')?.body).toEqual({ name: 'Google', config: { client_id: 'cid', client_secret: 'shh' } });
  expect(await screen.findByRole('status')).toHaveTextContent(/finish signing in/i);
});

test('a Google account whose sign-in expired can sign in again', async () => {
  serve({ 'POST /api/integrations/8/sign-in': [200, { auth_url: 'https://accounts.google.com/again' }] });
  const open = vi.spyOn(window, 'open').mockReturnValue(null);
  render(<IntegrationModal kind={googleKind} onClose={() => {}} onChanged={() => {}}
    integrations={[{ ...connected, id: 8, kind: 'google', name: 'Google', status: 'needs_auth', tools: [] }]} />);
  fireEvent.click(screen.getByRole('button', { name: 'Sign in to Google' }));
  await waitFor(() => expect(open).toHaveBeenCalledWith('https://accounts.google.com/again', '_blank', 'noopener'));
});

test('a Telegram bot waiting to be linked shows the link to tap and the code', () => {
  serve({});
  const telegramKind: IntegrationKind = { id: 'telegram', title: 'Telegram', description: '', icon: 'Send', fields: [] };
  render(<IntegrationModal kind={telegramKind} onClose={() => {}} onChanged={() => {}} integrations={[{
    ...connected, id: 4, kind: 'telegram', name: 'Telegram', status: 'needs_auth', tools: [],
    settings: { bot_username: 'nexus_test_bot', pairing_code: '123456' } }]} />);
  const open = screen.getByRole('link', { name: /Open @nexus_test_bot in Telegram/ });
  expect(open).toHaveAttribute('href', 'https://t.me/nexus_test_bot?start=123456');
  expect(screen.getByText(/\/start 123456/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Sign in to/ })).toBeNull();  // that's Google's
});

test('Slack shows its app manifest to copy, then the code to DM the bot', () => {
  serve({});
  const slackKind: IntegrationKind = { id: 'slack', title: 'Slack', description: '', icon: 'Hash', fields: [],
    manifest: '{"socket_mode_enabled": true}' };
  render(<IntegrationModal kind={slackKind} onClose={() => {}} onChanged={() => {}} integrations={[{
    ...connected, id: 5, kind: 'slack', name: 'Slack', status: 'needs_auth', tools: [],
    settings: { bot_username: 'nexus', pairing_code: '654321' } }]} />);
  expect(screen.getByText(/socket_mode_enabled/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Copy manifest' })).toBeInTheDocument();
  expect(screen.getByText(/654321/)).toBeInTheDocument();
});

test('Discord shows the invite link and the code to DM the bot', () => {
  serve({});
  const discordKind: IntegrationKind = { id: 'discord', title: 'Discord', description: '', icon: 'MessagesSquare', fields: [] };
  render(<IntegrationModal kind={discordKind} onClose={() => {}} onChanged={() => {}} integrations={[{
    ...connected, id: 6, kind: 'discord', name: 'Discord', status: 'needs_auth', tools: [],
    settings: { bot_username: 'nexus', pairing_code: '111222', invite_url: 'https://discord.com/oauth2/authorize?client_id=1' } }]} />);
  expect(screen.getByRole('link', { name: /Add @nexus to a server/ })).toHaveAttribute('href', 'https://discord.com/oauth2/authorize?client_id=1');
  expect(screen.getByText(/link 111222/)).toBeInTheDocument();
});

test('a link can open an integration straight away (/servers?connect=telegram)', async () => {
  const { MemoryRouter } = await import('react-router-dom');
  const { MarketplacePage } = await import('./MarketplacePage');
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const path = new URL(url).pathname;
    const body = path === '/api/integrations/kinds' ? [{ id: 'telegram', title: 'Telegram', description: 'Phone', icon: 'Send', fields: [] }]
      : path === '/api/marketplace' ? { items: [], status: { status: 'idle', count: 0, last_synced_at: null, error: null } }
      : path === '/api/marketplace/featured' ? { items: [] } : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
  render(<MemoryRouter initialEntries={['/servers?connect=telegram']}><MarketplacePage /></MemoryRouter>);
  expect(await screen.findByRole('dialog', { name: 'Telegram' })).toBeInTheDocument();
});

test('when linking is locked after wrong codes, it says so and offers a new code', async () => {
  const calls = serve({});
  const telegramKind: IntegrationKind = { id: 'telegram', title: 'Telegram', description: '', icon: 'Send', fields: [] };
  render(<IntegrationModal kind={telegramKind} onClose={() => {}} onChanged={() => {}} integrations={[{
    ...connected, id: 4, kind: 'telegram', name: 'Telegram', status: 'needs_auth', tools: [],
    settings: { bot_username: 'nexus_test_bot', pairing_code: '123456', pairing_locked: true } }]} />);
  expect(screen.getByText(/too many wrong codes/i)).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: /Open @nexus_test_bot/ })).toBeNull();  // the old code is no use now
  fireEvent.click(screen.getByRole('button', { name: 'Get a new code' }));
  await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.path === '/api/integrations/4/pairing-code')).toBe(true));
});
