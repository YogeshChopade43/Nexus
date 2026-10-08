import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { LibraryPanel } from './LibraryPanel';
import type { Library, RagDocument } from '../../types/rag';

afterEach(() => vi.unstubAllGlobals());

const library: Library = { id: 3, name: 'Policies', kind: 'library', documents: 1, ready: 0, created_at: '' };

function doc(patch: Partial<RagDocument>): RagDocument {
  return {
    id: 7, collection_id: 3, name: 'policy.pdf', mime: 'application/pdf', size_bytes: 1000, version: 1, status: 'ready',
    error: null, progress: 100, pages: 2, chars: 4000, chunk_count: 6, created_at: '', updated_at: '', ...patch,
  };
}

/** fetch stub: each path returns the next item of its list (the last one repeats). */
function serve(routes: Record<string, unknown[]>) {
  const calls: { path: string; method: string; body: unknown }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const path = new URL(url).pathname;
    calls.push({ path, method: init.method ?? 'GET', body: init.body });
    const queue = routes[`${init.method ?? 'GET'} ${path}`] ?? [];
    const body = queue.length > 1 ? queue.shift() : queue[0] ?? {};
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
  return calls;
}

test('shows processing progress, then ready after polling', async () => {
  serve({ 'GET /api/rag/collections/3/documents': [[doc({ status: 'processing', progress: 40 })], [doc({})]] });
  render(<LibraryPanel library={library} onChanged={() => {}} onDeleted={() => {}} pollMs={20} />);
  expect(await screen.findByText('Processing 40%')).toBeInTheDocument();
  expect(await screen.findByText('Ready')).toBeInTheDocument();
  expect(screen.getByText(/6 passages/)).toBeInTheDocument();
});

test('failed documents show why and can be retried', async () => {
  const calls = serve({
    'GET /api/rag/collections/3/documents': [[doc({ status: 'failed', error: 'scan.pdf has no selectable text' })]],
    'POST /api/rag/documents/7/retry': [doc({ status: 'queued' })],
  });
  render(<LibraryPanel library={library} onChanged={() => {}} onDeleted={() => {}} pollMs={20} />);
  expect(await screen.findByText('scan.pdf has no selectable text')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Retry policy.pdf' }));
  await waitFor(() => expect(calls.some(c => c.path === '/api/rag/documents/7/retry' && c.method === 'POST')).toBe(true));
});

test('uploading sends the files as multipart form data', async () => {
  const calls = serve({
    'GET /api/rag/collections/3/documents': [[]],
    'POST /api/rag/collections/3/documents': [[doc({ status: 'queued', name: 'a.md' })]],
  });
  const { container } = render(<LibraryPanel library={library} onChanged={() => {}} onDeleted={() => {}} pollMs={20} />);
  const input = container.querySelector('input[type=file]') as HTMLInputElement;
  const file = new File(['# hi'], 'a.md', { type: 'text/markdown' });
  fireEvent.change(input, { target: { files: [file] } });
  await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.path === '/api/rag/collections/3/documents')).toBe(true));
  const body = calls.find(c => c.method === 'POST')!.body as FormData;
  expect(body).toBeInstanceOf(FormData);
  expect((body.getAll('file')[0] as File).name).toBe('a.md');
});

test('try-a-search lists ranked passages with scores', async () => {
  serve({
    'GET /api/rag/collections/3/documents': [[doc({})]],
    'POST /api/rag/search': [{ sources: [{ chunk_id: 1, document_id: 7, document_name: 'policy.pdf', text: 'Shipping takes 5 days.',
      heading_path: 'Shipping', page_start: 2, page_end: 2, score: 0.91 }], insufficient: false, keyword_only: false, log_id: 4 }],
  });
  render(<LibraryPanel library={library} onChanged={() => {}} onDeleted={() => {}} pollMs={20} />);
  fireEvent.change(await screen.findByLabelText('Search this library'), { target: { value: 'shipping' } });
  fireEvent.submit(screen.getByLabelText('Search this library').closest('form')!);
  expect(await screen.findByText('Shipping takes 5 days.')).toBeInTheDocument();
  expect(screen.getByText(/0\.91/)).toBeInTheDocument();
});
