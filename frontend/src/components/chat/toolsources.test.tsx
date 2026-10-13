import { expect, test } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { Message } from './Message';
import type { ChatMessage } from '../../types/chat';

const reply: ChatMessage = {
  id: 'a1', role: 'assistant', content: 'You have 2 open issues.', timestamp: '2026-10-12T00:00:00Z', status: 'completed',
  events: [
    { type: 'tool_executed', tool_name: 'github__list_issues', app_id: 'github', summary: '2 results: Login bug, Typo',
      arguments: { state: 'open', assignee: 'YogeshChopade43' }, data: { items: [{ title: 'Login bug' }, { title: 'Typo' }] } },
  ],
};

test('answers built from app data show where they came from, with the raw result one click away', () => {
  render(<Message message={reply} />);
  const sources = screen.getByRole('region', { name: 'Sources from your apps' });
  const chip = screen.getByRole('button', { name: /List issues.*2 results/ });
  expect(sources).toContainElement(chip);
  expect(screen.queryByText(/"Login bug"/)).toBeNull();
  fireEvent.click(chip);
  expect(chip).toHaveAttribute('aria-expanded', 'true');
  expect(screen.getAllByRole('listitem').map(li => li.textContent)).toContain('assignee: YogeshChopade43');
  expect(screen.getByText(/"title": "Login bug"/)).toBeInTheDocument();
});

test('files a reply made are offered for download', () => {
  render(<Message message={{ ...reply, events: [{ type: 'tool_executed', tool_name: 'files__create_file', summary: 'Created issues.csv',
    data: { text: 'Created issues.csv', data: { file: { id: 'abcd1234abcd1234', name: 'issues.csv', size: 2048, url: '/api/files/abcd1234abcd1234/issues.csv' } } } }] }} />);
  const link = screen.getByRole('link', { name: /Download issues\.csv/ });
  expect(link.getAttribute('href')).toMatch(/\/api\/files\/abcd1234abcd1234\/issues\.csv$/);
  expect(link).toHaveAttribute('download');
  expect(screen.getByText(/2 KB/)).toBeInTheDocument();
});
