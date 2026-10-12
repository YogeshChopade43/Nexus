import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ContextMeter } from './ContextMeter';
import type { ChatMessage } from '../../types/chat';

afterEach(() => vi.unstubAllGlobals());

function serve(window: number | null) {
  const calls: string[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    calls.push(url);
    return new Response(JSON.stringify({ tokens: window, source: window ? 'model family' : null, model: 'gpt-4o-mini' }),
      { status: 200, headers: { 'content-type': 'application/json' } });
  }));
  return calls;
}

const reply = (context: number, estimated = false): ChatMessage => ({
  id: 'a', role: 'assistant', content: 'hi', timestamp: '2026-10-12T00:00:00Z',
  usage: { input_tokens: context + 500, output_tokens: 20, estimated, cost: null, context_tokens: context },
});

test('shows how full the context is, with details on click', async () => {
  const calls = serve(128_000);
  render(<ContextMeter messages={[reply(1_000), reply(64_000)]} providerId={3} />);
  const button = await screen.findByRole('button', { name: 'Context window: 50% used' });
  expect(calls[0]).toContain('provider_id=3');
  fireEvent.click(button);
  const panel = screen.getByRole('dialog', { name: 'Context window' });
  const n = new Intl.NumberFormat();  // the viewer's own digit grouping (e.g. 1,28,000 in India)
  expect(panel).toHaveTextContent(`${n.format(64_000)} of ${n.format(128_000)} tokens`);
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '50');
});

test('a nearly full context suggests a new chat', async () => {
  serve(128_000);
  render(<ContextMeter messages={[reply(120_000)]} providerId={null} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Context window: 94% used' }));
  expect(screen.getByRole('dialog')).toHaveTextContent(/start a new chat/i);
});

test('an unknown window still shows the tokens used', async () => {
  serve(null);
  render(<ContextMeter messages={[reply(5_000, true)]} providerId={null} />);
  fireEvent.click(await screen.findByRole('button', { name: `Context window: ≈${new Intl.NumberFormat().format(5_000)} tokens used` }));
  expect(screen.getByRole('dialog')).toHaveTextContent(/window size isn.t known/i);
});
