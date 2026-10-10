import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { CommandPalette } from './CommandPalette';

afterEach(() => vi.unstubAllGlobals());

function serve() {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const parsed = new URL(url);
    const body = parsed.pathname === '/api/agent/sessions' ? [{ id: 5, session_id: 's-5', title: 'Notion weekly summary' }]
      : parsed.pathname === '/api/workflows' ? [{ id: 13, name: 'Daily Medicine Reminder' }]
      : parsed.pathname === '/api/mcp/servers/' ? [{ id: 9, name: 'Notion', status: 'connected', enabled: true }]
      : parsed.pathname === '/api/rag/collections' ? [{ id: 1, kind: 'library', ready: 1 }]
      : parsed.pathname === '/api/rag/collections/1/documents' ? [{ id: 3, name: 'resume.pdf', status: 'ready' }] : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
}

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname}{location.search}</p>;
}

const page = (onOpenChat = vi.fn()) => {
  render(<MemoryRouter><CommandPalette onOpenChat={onOpenChat} /><Where /></MemoryRouter>);
  return onOpenChat;
};

test('Ctrl+K opens search across apps, chats, workflows, documents and pages', async () => {
  serve();
  page();
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
  const box = await screen.findByRole('combobox', { name: 'Search Nexus' });
  fireEvent.change(box, { target: { value: 'notion' } });
  expect(await screen.findByRole('option', { name: /Notion weekly summary/ })).toBeInTheDocument();
  expect(screen.getByRole('option', { name: /^App\s*Notion/ })).toBeInTheDocument();
  fireEvent.change(box, { target: { value: 'medicine' } });
  fireEvent.click(await screen.findByRole('option', { name: /Daily Medicine Reminder/ }));
  expect(screen.getByTestId('where')).toHaveTextContent('/workflows?open=13');
  expect(screen.queryByRole('combobox')).toBeNull();
});

test('keyboard: arrows and Enter open a chat; Escape closes', async () => {
  serve();
  const onOpenChat = page();
  fireEvent.keyDown(window, { key: 'k', metaKey: true });
  const box = await screen.findByRole('combobox', { name: 'Search Nexus' });
  fireEvent.change(box, { target: { value: 'weekly' } });
  await screen.findByRole('option', { name: /Notion weekly summary/ });
  fireEvent.keyDown(box, { key: 'Enter' });
  await waitFor(() => expect(onOpenChat).toHaveBeenCalledWith('s-5'));
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
  fireEvent.keyDown(await screen.findByRole('combobox'), { key: 'Escape' });
  expect(screen.queryByRole('combobox')).toBeNull();
});

test('pages and settings are found by name', async () => {
  serve();
  page();
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
  fireEvent.change(await screen.findByRole('combobox'), { target: { value: 'ai provider' } });
  fireEvent.click(await screen.findByRole('option', { name: /AI provider/ }));
  expect(screen.getByTestId('where')).toHaveTextContent('/settings?tab=ai');
});
