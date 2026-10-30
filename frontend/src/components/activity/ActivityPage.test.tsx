import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ActivityCard } from './ActivityPage';
import { activityService } from '../../services/activity';
import type { Activity } from '../../types/activity';

vi.mock('../../services/activity', () => ({
  activityService: { planUndo: vi.fn(), runUndo: vi.fn() },
}));

const approved: Activity = {
  id: '7', type: 'action_approved', title: 'Created issue LIN-42', description: '',
  timestamp: new Date().toISOString(), userId: '1',
  metadata: { tool: 'linear__create_issue', arguments: { title: 'Bug' }, app_id: 'linear' },
};
const plan = { tool: 'linear__close_issue', arguments: { id: 'LIN-42' }, explanation: 'Close issue LIN-42' };

describe('Undo on approved actions', () => {
  it('plans, confirms and runs the undo', async () => {
    vi.mocked(activityService.planUndo).mockResolvedValue(plan);
    vi.mocked(activityService.runUndo).mockResolvedValue({ undone: true });
    render(<ActivityCard activity={approved} />);
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(await screen.findByText('Close issue LIN-42')).toBeInTheDocument();
    expect(screen.getAllByText(/linear__close_issue/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: 'Undo it' }));
    await waitFor(() => expect(activityService.runUndo).toHaveBeenCalledWith('7', plan));
    expect(await screen.findByText('Undone')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
  });

  it('shows Undone and no button for an action already undone', () => {
    render(<ActivityCard activity={{ ...approved, metadata: { ...approved.metadata, undone_at: '2026-10-30T10:00:00Z' } }} />);
    expect(screen.getByText('Undone')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
  });

  it('shows why an action cannot be undone', async () => {
    vi.mocked(activityService.planUndo).mockImplementation(async () => { throw new Error("This can't be undone: a sent message cannot be unsent"); });
    render(<ActivityCard activity={approved} />);
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(await screen.findByText(/cannot be unsent/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo it' })).not.toBeInTheDocument();
  });

  it('has no Undo on other activity', () => {
    render(<ActivityCard activity={{ ...approved, type: 'workflow_completed' }} />);
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
  });
});
