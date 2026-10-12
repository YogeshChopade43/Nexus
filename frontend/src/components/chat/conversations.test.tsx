import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ConversationPanel, toMarkdown } from './ConversationPanel';
import type { AgentSession } from '../../types/chat';

afterEach(() => vi.unstubAllGlobals());

const session = (id: string, title: string, pinned = false): AgentSession => ({
  id: 1, session_id: id, title, messages: [], metadata: { pinned }, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
});

function serve() {
  const calls: { method: string; path: string; body: unknown }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ method: init.method ?? 'GET', path: new URL(url).pathname, body: init.body ? JSON.parse(init.body as string) : null });
    return new Response(JSON.stringify(session('a', 'x')), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
  return calls;
}

const panel = (props: Partial<Parameters<typeof ConversationPanel>[0]> = {}) => render(
  <ConversationPanel sessions={[session('a', 'Trip', true), session('b', 'Taxes')]} currentId={null}
    onSearch={() => {}} onOpen={() => {}} onDelete={async () => {}} onClose={() => {}} {...props} />);

test('rename saves the new title', async () => {
  const calls = serve();
  panel();
  fireEvent.click(screen.getByRole('button', { name: 'More actions for Taxes' }));
  fireEvent.click(screen.getByRole('menuitem', { name: 'Rename' }));
  const input = screen.getByRole('textbox', { name: 'Conversation title' });
  fireEvent.change(input, { target: { value: 'Taxes 2026' } });
  fireEvent.keyDown(input, { key: 'Enter' });
  fireEvent.blur(input);  // Enter blurs the field; blurring saves
  await waitFor(() => expect(calls[0]).toMatchObject({ method: 'PATCH', path: '/api/agent/sessions/b', body: { title: 'Taxes 2026' } }));
  expect(calls.filter(c => c.method === 'PATCH')).toHaveLength(1);
});

test('escape cancels a rename', () => {
  const calls = serve();
  panel();
  fireEvent.click(screen.getByRole('button', { name: 'More actions for Taxes' }));
  fireEvent.click(screen.getByRole('menuitem', { name: 'Rename' }));
  const input = screen.getByRole('textbox', { name: 'Conversation title' });
  fireEvent.change(input, { target: { value: 'Oops' } });
  fireEvent.keyDown(input, { key: 'Escape' });
  fireEvent.blur(input);
  expect(calls).toHaveLength(0);
  expect(screen.getByText('Taxes')).toBeInTheDocument();
});

test('pinned conversations are marked and can be unpinned', async () => {
  const calls = serve();
  panel();
  expect(screen.getByLabelText('Pinned')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'More actions for Trip' }));
  fireEvent.click(screen.getByRole('menuitem', { name: 'Unpin' }));
  await waitFor(() => expect(calls[0]).toMatchObject({ method: 'PATCH', body: { pinned: false } }));
});

test('several conversations can be deleted at once', async () => {
  serve();
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  const onDelete = vi.fn(async () => {});
  panel({ onDelete });
  fireEvent.click(screen.getByRole('button', { name: 'Select' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Select Trip' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Select Taxes' }));
  fireEvent.click(screen.getByRole('button', { name: 'Delete 2' }));
  await waitFor(() => expect(onDelete).toHaveBeenCalledTimes(2));
  expect(onDelete).toHaveBeenCalledWith('a');
  expect(onDelete).toHaveBeenCalledWith('b');
});

test('export writes the conversation as Markdown', () => {
  const md = toMarkdown({ ...session('a', 'Trip'), messages: [
    { role: 'user', content: 'Plan Goa' }, { role: 'assistant', content: 'Day 1: beach' }] });
  expect(md).toBe('# Trip\n\n**You:**\n\nPlan Goa\n\n**Nexus:**\n\nDay 1: beach\n');
});
