import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { Composer } from './Composer';

afterEach(() => vi.unstubAllGlobals());

function serve() {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const path = new URL(url).pathname;
    const body = path === '/api/mcp/servers/' ? [{ name: 'Notion', enabled: true, status: 'connected' }]
      : path === '/api/rag/collections' ? [{ id: 1, kind: 'library', ready: 1 }]
      : path === '/api/rag/collections/1/documents' ? [{ name: 'resume.pdf', status: 'ready' }] : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
}

const type = (text: string) => {
  const input = screen.getByLabelText('Message input') as HTMLTextAreaElement;
  fireEvent.change(input, { target: { value: text, selectionStart: text.length } });
  return input;
};

test('typing @ suggests apps; Enter picks one instead of sending', async () => {
  serve();
  const send = vi.fn();
  render(<Composer onSend={send} />);
  const input = type('Summarise @no');
  expect(await screen.findByRole('option', { name: /Notion/ })).toBeInTheDocument();
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(input.value).toBe('Summarise @Notion ');
  expect(send).not.toHaveBeenCalled();
  expect(screen.queryByRole('listbox')).toBeNull();
});

test('documents can be mentioned too, by clicking', async () => {
  serve();
  render(<Composer onSend={() => {}} />);
  const input = type('@res');
  fireEvent.click(await screen.findByRole('option', { name: /resume\.pdf/ }));
  expect(input.value).toBe('@resume.pdf ');
});

test('Escape closes the suggestions', async () => {
  serve();
  render(<Composer onSend={() => {}} />);
  const input = type('@');
  await screen.findByRole('listbox', { name: 'Mention an app or document' });
  fireEvent.keyDown(input, { key: 'Escape' });
  expect(screen.queryByRole('listbox')).toBeNull();
});

test('mentions are split out by name, ignoring case, only as whole names', async () => {
  const { splitMentions } = await import('./mentions');
  expect(splitMentions('Ask @github and @GitHub Actions about @githubber', ['GitHub', 'GitHub Actions'])).toEqual([
    { text: 'Ask ', mention: false }, { text: '@github', mention: true }, { text: ' and ', mention: false },
    { text: '@GitHub Actions', mention: true }, { text: ' about @githubber', mention: false },
  ]);
  expect(splitMentions('no mentions', ['GitHub'])).toEqual([{ text: 'no mentions', mention: false }]);
});

test('a picked app is highlighted in the message box', async () => {
  serve();
  render(<Composer onSend={() => {}} />);
  const input = type('Summarise @no');
  await screen.findByRole('option', { name: /Notion/ });
  fireEvent.keyDown(input, { key: 'Enter' });
  const mark = await screen.findByText('@Notion', { selector: 'mark' });
  expect(mark).toHaveAttribute('data-mention');
});
