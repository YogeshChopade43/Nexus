import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { StarterPrompts, starterPrompts } from './StarterPrompts';

afterEach(() => vi.unstubAllGlobals());

test('prompts come from the connected apps and documents', () => {
  const prompts = starterPrompts(['GitHub', 'Notion', 'Acme Tools'], 'YogeshChopade_2026.pdf');
  expect(prompts).toEqual([
    'List my open GitHub pull requests',
    'Summarise my most recent Notion pages',
    'What can you do with Acme Tools?',
    'Summarise YogeshChopade_2026.pdf',
  ]);
  expect(starterPrompts([], null)).toEqual(['What can you help me with?']);
});

test('clicking a prompt sends it', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const path = new URL(url).pathname;
    const body = path === '/api/mcp/servers/' ? [{ name: 'GitHub', status: 'connected', enabled: true }]
      : path === '/api/rag/collections' ? [] : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
  const pick = vi.fn();
  render(<StarterPrompts onPick={pick} />);
  fireEvent.click(await screen.findByRole('button', { name: 'List my open GitHub pull requests' }));
  expect(pick).toHaveBeenCalledWith('List my open GitHub pull requests');
});
