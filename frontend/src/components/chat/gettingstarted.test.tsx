import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { GettingStarted } from './GettingStarted';

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

function serve({ integrations = [] as unknown[], servers = [] as unknown[], libraries = [] as unknown[], briefing = false } = {}) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const path = new URL(url).pathname;
    const body = path === '/api/integrations' ? integrations : path === '/api/mcp/servers/' ? servers
      : path === '/api/rag/collections' ? libraries : path === '/api/briefing' ? { enabled: briefing } : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
}

const page = (hasLLM: boolean, onTry = vi.fn()) => {
  render(<MemoryRouter><GettingStarted hasLLM={hasLLM} onTry={onTry} /></MemoryRouter>);
  return onTry;
};

const goal = (name: RegExp) => screen.getByRole('listitem', { name });

test('a new user is asked what they want, each goal linking to its setup', async () => {
  serve();
  page(false);
  expect(await screen.findByText('What do you want Nexus for?')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /add an AI provider/i })).toHaveAttribute('href', '/settings?tab=ai');
  expect(within(goal(/Reminders on my phone/)).getByRole('link', { name: /Set up/ })).toHaveAttribute('href', '/servers?connect=telegram');
  expect(within(goal(/Answers from my documents/)).getByRole('link', { name: /Set up/ })).toHaveAttribute('href', '/knowledge');
  expect(within(goal(/Morning briefing/)).getByRole('link', { name: /Set up/ })).toHaveAttribute('href', '/dashboard');
});

test('goals that are ready offer to try them', async () => {
  serve({ integrations: [{ kind: 'telegram', status: 'connected' }], libraries: [{ kind: 'library', ready: 2 }] });
  const onTry = page(true);
  const phone = await screen.findByRole('listitem', { name: /Reminders on my phone/ });
  fireEvent.click(within(phone).getByRole('button', { name: /Try it/ }));
  expect(onTry).toHaveBeenCalledWith(expect.stringMatching(/remind me/i));
  expect(within(goal(/Answers from my documents/)).getByRole('button', { name: /Try it/ })).toBeInTheDocument();
  expect(within(goal(/Help with my email/)).getByRole('link', { name: /Set up/ })).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: /add an AI provider/i })).toBeNull();
});

test('the guide can be hidden for good', async () => {
  serve();
  page(true);
  fireEvent.click(await screen.findByRole('button', { name: 'Hide getting started' }));
  expect(screen.queryByText('What do you want Nexus for?')).toBeNull();
  expect(localStorage.getItem('nexus.gettingStarted.hidden')).toBe('1');
});
