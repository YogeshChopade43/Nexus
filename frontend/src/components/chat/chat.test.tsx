import { describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Composer, INLINE_CHARS } from './Composer';
import { Message } from './Message';
import type { ChatMessage } from '../../types/chat';

describe('Composer', () => {
  test('Enter sends the typed text (regression: it used to send the first render\'s empty value)', () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} />);
    const input = screen.getByLabelText('Message input');
    fireEvent.change(input, { target: { value: 'hello there' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSend).toHaveBeenCalledWith('hello there', [], []);
    expect(input).toHaveValue('');
  });

  test('Shift+Enter does not send', () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} />);
    const input = screen.getByLabelText('Message input');
    fireEvent.change(input, { target: { value: 'line one' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
  });

  test('small text files go inline, PDFs and big files to the knowledge base, other binaries are refused', async () => {
    const onSend = vi.fn();
    const { container } = render(<Composer onSend={onSend} />);
    const fileInput = container.querySelector('input[type=file]') as HTMLInputElement;
    const good = new File(['secret word'], 'notes.txt', { type: 'text/plain' });
    const bad = new File([new Uint8Array([0x89, 0x00, 0x01])], 'image.png', { type: 'image/png' });
    const pdf = new File(['%PDF-1.4'], 'report.pdf', { type: 'application/pdf' });
    const big = new File(['x'.repeat(INLINE_CHARS + 1)], 'huge.log', { type: 'text/plain' });
    fireEvent.change(fileInput, { target: { files: [good, bad, pdf, big] } });
    await screen.findByText('notes.txt');
    expect(screen.getByText("image.png isn't a text file or PDF")).toBeInTheDocument();
    expect(screen.getAllByText('→ knowledge')).toHaveLength(2);
    fireEvent.click(screen.getByLabelText('Send message'));
    expect(onSend).toHaveBeenCalledWith('', [{ name: 'notes.txt', content: 'secret word' }], [pdf, big]);
  });

  test('while a reply is written, Stop replaces Send', () => {
    const onStop = vi.fn();
    render(<Composer onSend={() => {}} running onStop={onStop} disabled />);
    expect(screen.queryByLabelText('Send message')).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Stop'));
    expect(onStop).toHaveBeenCalled();
  });
});

const base: ChatMessage = { id: 'm1', role: 'assistant', content: '', timestamp: new Date().toISOString() };

describe('Message', () => {
  test('approval card shows the tool and its arguments and reports the answer', () => {
    const onApprove = vi.fn();
    render(
      <Message
        message={{ ...base, status: 'needs_approval', content: 'Nexus wants to run…', pendingAction: { tool: 'slack__send', arguments: { text: 'hi' } } }}
        onApprove={onApprove}
      />,
    );
    expect(screen.getByRole('group', { name: 'Approval needed' })).toHaveTextContent('slack__send');
    expect(screen.getByText(/"text": "hi"/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('Deny'));
    expect(onApprove).toHaveBeenCalledWith(false);
  });

  test('an older approval card has no buttons', () => {
    render(<Message message={{ ...base, status: 'needs_approval', pendingAction: { tool: 't', arguments: {} } }} />);
    expect(screen.queryByText('Approve')).not.toBeInTheDocument();
    expect(screen.getByText('This request is no longer waiting.')).toBeInTheDocument();
  });

  test('a running reply shows live tool activity', () => {
    render(<Message message={{ ...base, status: 'running', activity: [{ tool: 'notion__search', state: 'running' }, { tool: 'echo', state: 'ok', summary: 'done' }] }} />);
    expect(screen.getByRole('list', { name: 'Tool activity' })).toHaveTextContent('notion__search');
    expect(screen.getByText('Nexus is thinking')).toBeInTheDocument();
  });

  test('declined tools are listed', async () => {
    render(<Message message={{ ...base, content: 'Not done.', events: [{ type: 'tool_declined', tool_name: 'files__delete' }] }} />);
    await waitFor(() => expect(screen.getByText('files__delete')).toBeInTheDocument());
    expect(screen.getByText(/declined by you/)).toBeInTheDocument();
  });
});
