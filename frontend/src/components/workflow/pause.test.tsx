import { expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { WorkflowList } from './WorkflowList';
import type { Workflow } from '../../types/workflow';

const wf = (id: number, name: string, type: string, isActive: boolean) =>
  ({ id, name, description: '', isActive, trigger_config: { type }, nodes: [], edges: [], steps: [] }) as unknown as Workflow;

test('automatic workflows can be stopped and started from the menu; manual ones have neither', () => {
  const onToggleActive = vi.fn();
  render(<WorkflowList workflows={[wf(1, 'Pills', 'recurrence', true), wf(2, 'Digest', 'poll', false), wf(3, 'Once', 'manual', true)]}
    selectedWorkflow={null} onSelect={() => {}} onCreate={() => {}} onEdit={() => {}} onDelete={() => {}} onExecute={() => {}}
    onToggleActive={onToggleActive} />);
  fireEvent.click(screen.getByRole('button', { name: 'More actions for Pills' }));
  fireEvent.click(screen.getByRole('menuitem', { name: 'Stop' }));
  expect(onToggleActive).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }));
  fireEvent.click(screen.getByRole('button', { name: 'More actions for Digest' }));
  expect(screen.getByRole('menuitem', { name: 'Start' })).toBeInTheDocument();
  fireEvent.keyDown(document, { key: 'Escape' });
  fireEvent.click(screen.getByRole('button', { name: 'More actions for Once' }));
  expect(screen.queryByRole('menuitem', { name: /^(Stop|Start)$/ })).toBeNull();
});

test('the last run status is left to the run history, not shown beside the name', () => {
  render(<WorkflowList workflows={[{ ...wf(1, 'Pills', 'recurrence', true), last_status: 'completed' } as Workflow]}
    selectedWorkflow={null} onSelect={() => {}} onCreate={() => {}} onEdit={() => {}} onDelete={() => {}} onExecute={() => {}}
    onToggleActive={() => {}} />);
  expect(screen.queryByText('completed')).toBeNull();
});
