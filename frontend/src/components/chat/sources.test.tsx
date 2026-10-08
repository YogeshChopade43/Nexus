import { afterEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { Sources } from './Sources';
import type { Citation } from '../../types/rag';

afterEach(() => vi.unstubAllGlobals());

const citations: Citation[] = [
  { n: 1, document_id: 7, document_name: 'policy.pdf', heading_path: 'Shipping', pages: '2', chunk_id: 11, snippet: 'Shipping takes 5 days.' },
  { n: 2, document_id: 8, document_name: 'faq.md', heading_path: '', pages: '', chunk_id: 12, snippet: 'Refunds in 30 days.' },
];

function stubFetch() {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const path = new URL(url).pathname;
    const body = path.includes('/chunks/')
      ? { chunk: { id: 11, document_id: 7, document_name: 'policy.pdf', text: 'Shipping to Pune takes 5 business days.',
          heading_path: 'Shipping', page_start: 2, page_end: 2 }, before: { id: 10, text: 'Earlier text.' }, after: null }
      : { id: 1 };
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
}

test('chips per citation; opening one shows the passage with its neighbours', async () => {
  stubFetch();
  render(<Sources citations={citations} />);
  expect(screen.getByRole('button', { name: /\[1\] policy\.pdf · p\. 2/ })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /\[2\] faq\.md/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /\[1\] policy\.pdf/ }));
  const panel = await screen.findByRole('dialog', { name: 'Source' });
  expect(await screen.findByText('Shipping to Pune takes 5 business days.')).toBeInTheDocument();
  expect(panel).toHaveTextContent('Earlier text.');
});

test('no answer feedback buttons', () => {
  render(<Sources citations={citations} />);
  expect(screen.queryByRole('button', { name: 'Helpful answer' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'Not helpful' })).toBeNull();
});
