import { expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { QuestionCard } from './QuestionCard';
import { Message } from './Message';
import type { AgentQuestion, ChatMessage } from '../../types/chat';

const alerts: AgentQuestion = {
  question: 'Where should the reminder reach you?', header: 'Alerts', multi_select: false,
  options: [{ label: 'Nexus pop-up', description: "Shows in Nexus while it's open" }, { label: 'Slack', description: 'A message in a channel' }],
};
const days: AgentQuestion = {
  question: 'Which days?', header: 'Days', multi_select: true,
  options: [{ label: 'Weekdays', description: '' }, { label: 'Weekends', description: '' }],
};

test('one click per question, then send', () => {
  const submit = vi.fn();
  render(<QuestionCard questions={[alerts, days]} onSubmit={submit} />);
  expect(screen.getByText('Alerts')).toBeInTheDocument();
  expect(screen.getByText("Shows in Nexus while it's open")).toBeInTheDocument();
  const send = screen.getByRole('button', { name: 'Send answers' });
  expect(send).toBeDisabled();  // every question needs an answer
  fireEvent.click(screen.getByRole('radio', { name: /Slack/ }));
  fireEvent.click(screen.getByRole('checkbox', { name: /Weekdays/ }));
  fireEvent.click(screen.getByRole('checkbox', { name: /Weekends/ }));
  fireEvent.click(send);
  expect(submit).toHaveBeenCalledWith({ 'Where should the reminder reach you?': 'Slack', 'Which days?': ['Weekdays', 'Weekends'] });
});

test('Other lets them type their own answer', () => {
  const submit = vi.fn();
  render(<QuestionCard questions={[alerts]} onSubmit={submit} />);
  fireEvent.click(screen.getByRole('radio', { name: 'Other' }));
  fireEvent.change(screen.getByLabelText('Your answer to: Where should the reminder reach you?'), { target: { value: 'Text my phone' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send answers' }));
  expect(submit).toHaveBeenCalledWith({ 'Where should the reminder reach you?': 'Text my phone' });
});

test('a waiting reply shows the card and passes the answers on', () => {
  const onAnswer = vi.fn();
  const message: ChatMessage = {
    id: '1', role: 'assistant', content: 'Nexus has a question for you.', timestamp: new Date().toISOString(),
    status: 'needs_input', pendingQuestion: { questions: [alerts] },
  };
  render(<Message message={message} onAnswer={onAnswer} />);
  expect(screen.getByRole('group', { name: 'Questions from Nexus' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('radio', { name: /Nexus pop-up/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Send answers' }));
  expect(onAnswer).toHaveBeenCalledWith({ 'Where should the reminder reach you?': 'Nexus pop-up' });
});

test('answered questions show what was chosen', () => {
  const message: ChatMessage = {
    id: '2', role: 'assistant', content: 'Reminder set.', timestamp: new Date().toISOString(), status: 'completed',
    events: [{ type: 'user_answered', answers: { 'Where should the reminder reach you?': 'Slack' } }],
  };
  render(<Message message={message} />);
  expect(screen.getByText(/Where should the reminder reach you\?/)).toBeInTheDocument();
  expect(screen.getByText(/Slack/)).toBeInTheDocument();
});

test('approval cards read like a form, not JSON', async () => {
  const { ApprovalDetails } = await import('./ApprovalDetails');
  render(<ApprovalDetails arguments={{
    description: 'Every day at 2 pm, remind me to take my medicines as a Nexus pop-up',
    max_results: 10, include_archived: false, labels: ['bug', 'urgent'], filter: { state: 'open' },
  }} />);
  expect(screen.getByText('Description')).toBeInTheDocument();
  expect(screen.getByText('Every day at 2 pm, remind me to take my medicines as a Nexus pop-up')).toBeInTheDocument();
  expect(screen.getByText('Max results')).toBeInTheDocument();
  expect(screen.getByText('10')).toBeInTheDocument();
  expect(screen.getByText('No')).toBeInTheDocument();
  expect(screen.getByText('bug, urgent')).toBeInTheDocument();
  expect(screen.getByText('State: open')).toBeInTheDocument();
});
