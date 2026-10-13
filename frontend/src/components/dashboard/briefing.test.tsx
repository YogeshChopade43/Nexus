import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BriefingCard } from './BriefingCard';

afterEach(() => vi.unstubAllGlobals());

const off = { enabled: false, workflow_id: null, time: '08:00', weekdays_only: true, sections: ['calendar', 'email', 'apps', 'feeds'], notes: '', next_run_at: null };

function serve() {
  const calls: { method: string; path: string; body: unknown }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET';
    const path = new URL(url).pathname;
    const body = init.body ? JSON.parse(init.body as string) : null;
    calls.push({ method, path, body });
    const reply = path === '/api/briefing/send-now' ? { text: '## Calendar\n- 10:00 Standup' }
      : method === 'PUT' ? { ...off, ...body, enabled: true, workflow_id: 5, next_run_at: '2026-10-13T07:30:00+05:30' } : off;
    return new Response(JSON.stringify(reply), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
  return calls;
}

test('setting up the briefing saves the chosen time and sections', async () => {
  const calls = serve();
  render(<BriefingCard />);
  fireEvent.click(await screen.findByRole('button', { name: 'Set up' }));
  fireEvent.change(screen.getByLabelText('Time'), { target: { value: '07:30' } });
  fireEvent.click(screen.getByRole('checkbox', { name: /New posts in my feeds/ }));
  fireEvent.change(screen.getByLabelText(/Anything else/), { target: { value: 'Skip newsletters' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(calls.find(c => c.method === 'PUT')).toBeDefined());
  expect(calls.find(c => c.method === 'PUT')!.body).toEqual({
    enabled: true, time: '07:30', weekdays_only: true, sections: ['calendar', 'email', 'apps'], notes: 'Skip newsletters' });
  expect(await screen.findByText(/Next:/)).toBeInTheDocument();
});

test('send one now shows the briefing it sent', async () => {
  serve();
  render(<BriefingCard />);
  fireEvent.click(await screen.findByRole('button', { name: 'Set up' }));
  fireEvent.click(screen.getByRole('button', { name: 'Send one now' }));
  expect(await screen.findByText('10:00 Standup')).toBeInTheDocument();
});
