import { describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { Message } from './Message';
import { toCsv } from './Markdown';
import type { ChatMessage } from '../../types/chat';

const base: ChatMessage = { id: 'm1', role: 'assistant', content: '', timestamp: new Date().toISOString() };

describe('replies', () => {
  test('render Markdown: tables with copy/CSV, code blocks with copy, no raw HTML', () => {
    const text = [
      '**Bold** and `code`', '',
      '| Name | Count |', '|---|---|', '| a, b | 2 |', '',
      '```python', 'print(1)', '```', '',
      '<script>alert(1)</script>',
    ].join('\n');
    const { container } = render(<Message message={{ ...base, content: text }} />);
    expect(screen.getByText('Bold').tagName).toBe('STRONG');
    expect(screen.getByRole('table')).toHaveTextContent('Count');
    expect(screen.getByLabelText('Download table as CSV')).toBeInTheDocument();
    expect(screen.getByText('python')).toBeInTheDocument();
    expect(screen.getByLabelText('Copy code')).toBeInTheDocument();
    expect(container.querySelector('script')).toBeNull();
  });

  test('CSV quoting', () => {
    expect(toCsv([['Name', 'Note'], ['a, b', 'say "hi"']])).toBe('Name,Note\n"a, b","say ""hi"""');
  });

  test('your own messages stay plain text', () => {
    render(<Message message={{ ...base, role: 'user', content: '**not bold**' }} />);
    expect(screen.getByText('**not bold**')).toBeInTheDocument();
  });

  test('usage and retry', () => {
    const onRetry = vi.fn();
    render(<Message message={{ ...base, content: 'Hi', usage: { input_tokens: 1200, output_tokens: 34, estimated: false, cost: 0.0213 } }} onRetry={onRetry} />);
    expect(screen.getByText('1,234 tokens · $0.02')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Retry'));
    expect(onRetry).toHaveBeenCalled();
  });

  test('edit puts the question (without the attachment line) in a box and sends the new text', () => {
    const onEdit = vi.fn();
    render(<Message message={{ ...base, id: 'u1', role: 'user', content: 'old question\n\n📎 notes.txt' }} onEdit={onEdit} />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit message' }));
    const box = screen.getByRole('textbox', { name: 'Edit message' });
    expect(box).toHaveValue('old question');
    fireEvent.change(box, { target: { value: 'new question' } });
    fireEvent.click(screen.getByText('Send'));
    expect(onEdit).toHaveBeenCalledWith('new question');
  });
});
