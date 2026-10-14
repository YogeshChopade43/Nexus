import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { Message } from './Message';
import type { ChatMessage } from '../../types/chat';

const base: ChatMessage = { id: 'm1', role: 'assistant', content: '', timestamp: new Date().toISOString() };
const ref = (name: string) => ({ id: '0123456789abcdef', name, size: 2048, url: `/api/files/0123456789abcdef/${name}` });

function serve(preview: unknown) {
  const fetchMock = vi.fn(async (_url: string) => new Response(JSON.stringify(preview), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

test('a file the reply made opens in a preview, and can still be downloaded', async () => {
  const fetchMock = serve({ kind: 'table', sheets: [{ name: 'Sheet', truncated: false, rows: [['Date', 'Exercise'], ['2026-10-13', 'Squat']] }] });
  render(<Message message={{ ...base, content: 'Here you go.', events: [
    { type: 'tool_executed', tool_name: 'files__create_file', data: { data: { file: ref('gym.xlsx') } } }] }} />);
  expect(screen.getByRole('link', { name: 'Download gym.xlsx' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Preview gym.xlsx' }));
  const dialog = await screen.findByRole('dialog');
  expect(await within(dialog).findByRole('cell', { name: 'Squat' })).toBeInTheDocument();
  expect(within(dialog).getByRole('columnheader', { name: 'Exercise' })).toBeInTheDocument();
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/api/files/0123456789abcdef/gym.xlsx/preview'))).toBe(true);
});

test('files you attached show under your message, without their text pasted in', async () => {
  serve({ kind: 'text', text: 'line one', truncated: false });
  const content = "summarise this\n\nAttached file 'notes.txt':\n```\nline one\n```";
  render(<Message message={{ ...base, role: 'user', content, files: [ref('notes.txt')] }} />);
  expect(screen.getByText('summarise this')).toBeInTheDocument();
  expect(screen.queryByText(/Attached file/)).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Preview notes.txt' }));
  expect(await within(await screen.findByRole('dialog')).findByText('line one')).toBeInTheDocument();
});

test('PDFs open in the browser viewer; web pages run sandboxed', async () => {
  serve({ kind: 'pdf' });
  const { unmount } = render(<Message message={{ ...base, role: 'user', content: 'cv', files: [ref('cv.pdf')] }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Preview cv.pdf' }));
  const pdf = await within(await screen.findByRole('dialog')).findByTitle('cv.pdf');
  expect(pdf.getAttribute('src')).toContain('/api/files/0123456789abcdef/cv.pdf?inline=1');
  unmount();

  serve({ kind: 'html', text: '<b>hi</b><script>alert(1)</script>', truncated: false });
  render(<Message message={{ ...base, role: 'user', content: 'page', files: [ref('page.html')] }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Preview page.html' }));
  const page = await within(await screen.findByRole('dialog')).findByTitle('page.html');
  expect(page.getAttribute('sandbox')).toBe('');  // no scripts, no access to Nexus
  expect(page.getAttribute('srcdoc')).toContain('<b>hi</b>');
});

test('pictures (like a browser screenshot) show as an image', async () => {
  serve({ kind: 'image' });
  render(<Message message={{ ...base, content: 'Done.', events: [
    { type: 'tool_executed', tool_name: 'browser__screenshot', data: { data: { file: ref('screenshot-shop.png') } } }] }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Preview screenshot-shop.png' }));
  const image = await within(await screen.findByRole('dialog')).findByRole('img', { name: 'screenshot-shop.png' });
  expect(image.getAttribute('src')).toContain('/api/files/0123456789abcdef/screenshot-shop.png?inline=1');
});
