import { beforeEach, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { WorkflowList } from './WorkflowList';
import type { Workflow } from '../../types/workflow';

const wf = (id: number, name: string, folder = '') =>
  ({ id, name, description: '', folder, isActive: true, trigger_config: { type: 'manual' }, nodes: [], edges: [], steps: [], version: 1 }) as unknown as Workflow;

const all = [wf(1, 'Pills', 'Health'), wf(2, 'Water', 'Health'), wf(3, 'Weekly report', 'Work'), wf(4, 'Loose one'),
  wf(5, 'Standup notes', 'Work'), wf(6, 'Gym log', 'Health')];

function list(onMove = vi.fn()) {
  render(<WorkflowList workflows={all} selectedWorkflow={null} onSelect={() => {}} onCreate={() => {}} onEdit={() => {}}
    onDelete={() => {}} onExecute={() => {}} onToggleActive={() => {}} onMove={onMove} />);
  return onMove;
}

beforeEach(() => localStorage.clear());

test('workflows are grouped under their folders, which fold away', () => {
  list();
  const health = screen.getByRole('button', { name: /^Health/ });
  expect(health).toHaveTextContent('3');
  expect(screen.getByRole('button', { name: /^Work/ })).toHaveTextContent('2');
  expect(screen.getByText('Loose one')).toBeInTheDocument();  // not in a folder: still listed
  fireEvent.click(health);
  expect(health).toHaveAttribute('aria-expanded', 'false');
  expect(screen.queryByText('Pills')).toBeNull();
  expect(screen.getByText('Weekly report')).toBeInTheDocument();
});

test('search finds workflows by name or folder', () => {
  list();
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search workflows' }), { target: { value: 'work' } });
  expect(screen.getByText('Weekly report')).toBeInTheDocument();
  expect(screen.getByText('Standup notes')).toBeInTheDocument();  // its folder matches
  expect(screen.queryByText('Pills')).toBeNull();
});

test('a workflow moves into an existing or new folder, or out of one', () => {
  const onMove = list();
  fireEvent.click(screen.getByRole('button', { name: 'More actions for Loose one' }));
  fireEvent.click(screen.getByRole('menuitem', { name: 'Move to folder' }));
  const dialog = screen.getByRole('dialog');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Health' }));
  expect(onMove).toHaveBeenCalledWith(expect.objectContaining({ id: 4 }), 'Health');

  fireEvent.click(screen.getByRole('button', { name: 'More actions for Loose one' }));
  fireEvent.click(screen.getByRole('menuitem', { name: 'Move to folder' }));
  fireEvent.change(within(screen.getByRole('dialog')).getByRole('textbox', { name: 'New folder' }), { target: { value: 'Finance' } });
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Move' }));
  expect(onMove).toHaveBeenCalledWith(expect.objectContaining({ id: 4 }), 'Finance');

  fireEvent.click(screen.getByRole('button', { name: 'More actions for Pills' }));
  fireEvent.click(screen.getByRole('menuitem', { name: 'Move to folder' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Take out of “Health”' }));
  expect(onMove).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }), '');
});

function manage(extra: Record<string, unknown> = {}) {
  const calls = { onMove: vi.fn(), onCreateFolder: vi.fn(async () => {}), onRenameFolder: vi.fn(async () => {}), onDeleteFolder: vi.fn() };
  render(<WorkflowList workflows={all} folders={['Finance']} selectedWorkflow={null} onSelect={() => {}} onCreate={() => {}}
    onEdit={() => {}} onDelete={() => {}} onExecute={() => {}} onToggleActive={() => {}} {...calls} {...extra} />);
  return calls;
}

test('a New folder button sits in the list itself; new folders show while still empty', async () => {
  const { onCreateFolder } = manage();
  expect(screen.getByRole('button', { name: /^Finance/ })).toHaveTextContent('0');
  expect(screen.getByText(/Drag a workflow here/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'New folder' }));
  fireEvent.change(within(screen.getByRole('dialog')).getByRole('textbox', { name: 'Folder name' }), { target: { value: 'Travel' } });
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Create' }));
  expect(onCreateFolder).toHaveBeenCalledWith('Travel');
});

test('dragging a workflow onto a folder files it there', () => {
  const { onMove } = manage();
  fireEvent.dragStart(screen.getByText('Loose one'));
  fireEvent.dragOver(screen.getByRole('button', { name: /^Finance/ }));
  fireEvent.drop(screen.getByRole('button', { name: /^Finance/ }));
  expect(onMove).toHaveBeenCalledWith(expect.objectContaining({ id: 4 }), 'Finance');
});

test('a folder can be renamed or deleted from its heading', () => {
  const { onRenameFolder, onDeleteFolder } = manage();
  fireEvent.click(screen.getByRole('button', { name: 'Folder actions for Health' }));
  fireEvent.click(screen.getByRole('menuitem', { name: 'Rename' }));
  const name = within(screen.getByRole('dialog')).getByRole('textbox', { name: 'Folder name' });
  expect(name).toHaveValue('Health');
  fireEvent.change(name, { target: { value: 'Wellbeing' } });
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Rename' }));
  expect(onRenameFolder).toHaveBeenCalledWith('Health', 'Wellbeing');
  fireEvent.click(screen.getByRole('button', { name: 'Folder actions for Work' }));
  fireEvent.click(screen.getByRole('menuitem', { name: 'Delete folder' }));
  expect(onDeleteFolder).toHaveBeenCalledWith('Work');
});
