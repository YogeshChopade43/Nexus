import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { RunOnce, RunOnceBanner } from './RunOnce';

const HOUR = 3_600_000;
const iso = (ms: number) => new Date(ms).toISOString();
const birthday = { id: 1, workflowId: 41, name: 'Birthday message to Mom', kind: 'at', at: iso(Date.now() + 30 * 24 * HOUR),
  days: null, enabled: true, status: 'scheduled', runsAt: iso(Date.now() + 30 * 24 * HOUR), quietSince: null, warnedAt: null, ranAt: null, missedAt: null };
const safety = { id: 2, workflowId: 42, name: 'Share documents with family', kind: 'quiet', at: null, days: 14, enabled: true,
  status: 'armed', runsAt: iso(Date.now() + 11 * 24 * HOUR), quietSince: iso(Date.now() - 3 * 24 * HOUR - HOUR), warnedAt: null, ranAt: null, missedAt: null };

const TELEGRAM = { id: 3, kind: 'telegram', name: 'Telegram', slug: 'telegram', enabled: true, status: 'connected', settings: {},
  created_at: '', tools: [{ name: 'telegram__send_message', remote_name: 'send_message', description: 'Send the user a Telegram message',
    policy: 'allow', required: ['text'] }] };

function serve(items: unknown[], extra: Record<string, unknown> = {}) {
  const calls: { url: string; method: string; body?: unknown }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200, headers: { 'content-type': 'application/json' } });
    if (String(url).includes('/api/mcp/servers')) return json([]);
    if (String(url).includes('/api/integrations')) return json([TELEGRAM]);
    if (String(url).includes('/api/tools')) return json({ tools: [{ tool_name: 'telegram__send_message', name: 'send_message', app_id: 'telegram',
      description: 'Send the user a Telegram message', parameters: { type: 'object', properties: { text: { type: 'string' } }, required: ['text'] } }] });
    if (String(url).includes('/api/workflows')) return json([]);
    const body = init?.method === 'POST' && String(url).endsWith('/api/run-once') ? { ...safety, id: 9 }
      : init?.method === 'DELETE' ? null
      : { items, lastCheckIn: iso(Date.now() - 2 * HOUR), channels: ['Telegram'], ...extra };
    return body === null ? new Response(null, { status: 204 })
      : new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
  return calls;
}

afterEach(() => vi.unstubAllGlobals());
const page = () => render(<MemoryRouter><RunOnce /></MemoryRouter>);

test('with none yet, an example starts a new one already filled in', async () => {
  serve([]);
  page();
  fireEvent.click(await screen.findByRole('button', { name: /Share important info if I go quiet/ }));
  const dialog = screen.getByRole('dialog', { name: 'New run-once' });
  expect(within(dialog).getByRole('radio', { name: /If I go quiet/ })).toBeChecked();
  expect(within(dialog).getByLabelText('Name')).toHaveValue('Share important info with family');
  expect(within(dialog).getByRole('button', { name: 'Create' })).toBeDisabled();  // until it has a step
  expect(within(dialog).getByRole('button', { name: /Add a step/ })).toBeInTheDocument();
});

test('each one says when it runs, with its steps a click away', async () => {
  serve([birthday, safety]);
  page();
  expect(await screen.findByText('Birthday message to Mom')).toBeInTheDocument();
  expect(screen.getByText(/in 30 days/)).toBeInTheDocument();
  expect(screen.getByRole('progressbar', { name: /3 of 14 quiet days/ })).toBeInTheDocument();
  expect(screen.getAllByRole('link', { name: /Edit steps/ })[0]).toHaveAttribute('href', '/workflows?open=41');
});

test("I'm here checks in and says so", async () => {
  const calls = serve([safety]);
  page();
  fireEvent.click(await screen.findByRole('button', { name: "I'm here" }));
  await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/api/run-once/check-in'))).toBe(true));
  expect(await screen.findByRole('status')).toHaveTextContent(/Checked in/);
});

test('one can be paused or deleted', async () => {
  const calls = serve([birthday]);
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  page();
  fireEvent.click(await screen.findByRole('button', { name: 'Pause Birthday message to Mom' }));
  await waitFor(() => expect(calls.find(c => c.method === 'PATCH')?.body).toEqual({ enabled: false }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete Birthday message to Mom' }));
  await waitFor(() => expect(calls.some(c => c.method === 'DELETE' && c.url.endsWith('/api/run-once/1'))).toBe(true));
});

test('the banner shows only while one is warning', async () => {
  serve([{ ...safety, status: 'warning', warnedAt: iso(Date.now()) }]);
  render(<MemoryRouter><RunOnceBanner /></MemoryRouter>);
  expect(await screen.findByRole('alert')).toHaveTextContent('Share documents with family');
});

test('one with no steps yet says so', async () => {
  serve([{ ...birthday, steps: 0 }, { ...safety, steps: 2 }]);
  page();
  expect(await screen.findAllByText(/No steps yet/)).toHaveLength(1);
});

test('what happens is added while making it: pick an action, fill it in, create', async () => {
  const calls = serve([]);
  page();
  fireEvent.click(await screen.findByRole('button', { name: 'New run-once' }));
  const dialog = screen.getByRole('dialog', { name: 'New run-once' });
  fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Birthday' } });
  fireEvent.change(within(dialog).getByLabelText('Date and time'), { target: { value: '2031-01-01T09:00' } });
  expect(within(dialog).getByRole('button', { name: 'Create' })).toBeDisabled();  // nothing to do yet
  fireEvent.click(within(dialog).getByRole('button', { name: /Add a step/ }));
  const picker = await screen.findByRole('dialog', { name: 'Choose an operation' });
  const app = await within(picker).findByRole('button', { name: /^Telegram/ });
  if (!within(picker).queryByRole('button', { name: /Send the user a Telegram message/ })) fireEvent.click(app);  // expand it if folded
  fireEvent.click(await within(picker).findByRole('button', { name: /Send the user a Telegram message/ }));
  fireEvent.change(await within(dialog).findByRole('textbox', { name: /Text/ }), { target: { value: 'Happy Birthday' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Create' }));
  await waitFor(() => expect(calls.find(c => c.method === 'POST')?.body).toMatchObject({
    name: 'Birthday', kind: 'at',
    nodes: [{ type: 'action', config: { tool: 'telegram__send_message', parameters: { text: 'Happy Birthday' } } }],
  }));
});
