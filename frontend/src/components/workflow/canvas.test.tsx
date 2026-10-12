import { afterEach, beforeAll, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { WorkflowBuilder, type WorkflowSaveData } from './WorkflowBuilder';
import { FlowEditor } from './FlowEditor';
import type { Workflow, WorkflowEdge, WorkflowNode } from '../../types/workflow';

// React Flow measures elements; jsdom has no layout (stubs from React Flow's testing guide).
beforeAll(() => {
  class ResizeObserver {
    constructor(private callback: ResizeObserverCallback) {}
    observe(target: Element) { this.callback([{ target, contentRect: { width: 1000, height: 600 } } as unknown as ResizeObserverEntry], this as unknown as globalThis.ResizeObserver); }
    unobserve() {}
    disconnect() {}
  }
  class DOMMatrixReadOnly {
    m22: number;
    constructor(transform?: string) { this.m22 = Number(transform?.match(/scale\(([\d.]+)\)/)?.[1] ?? 1); }
  }
  Object.assign(globalThis, { ResizeObserver, DOMMatrixReadOnly });
  Object.defineProperties(HTMLElement.prototype, {
    offsetHeight: { configurable: true, get() { return parseFloat(this.style.height) || 64; } },
    offsetWidth: { configurable: true, get() { return parseFloat(this.style.width) || 220; } },
  });
});

afterEach(() => vi.unstubAllGlobals());

function serve() {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const path = new URL(url).pathname;
    const body = path.endsWith('/runs') ? { runs: [] } : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  }));
}

const node = (id: string, type: WorkflowNode['type'], name: string, config: Record<string, unknown> = {}): WorkflowNode => ({ id, type, name, config });
const edge = (source: string, target: string, sourceHandle?: string): WorkflowEdge =>
  ({ id: `${source}-${target}`, source, target, ...(sourceHandle ? { sourceHandle } : {}) });

const workflow = (nodes: WorkflowNode[], edges: WorkflowEdge[]) => ({
  id: 9, name: 'Pills', description: '', nodes, edges, steps: [], isActive: true, trigger_config: { type: 'manual' },
}) as unknown as Workflow;

const trigger = node('trigger_1', 'trigger', 'Trigger', { trigger_type: 'manual' });

function builder(wf: Workflow, onSave = vi.fn(async (_data: WorkflowSaveData) => null)) {
  render(<MemoryRouter><WorkflowBuilder workflow={wf} onSave={onSave} onCancel={() => {}} tools={[]} llmProviders={[]} /></MemoryRouter>);
  return onSave;
}

test('the canvas shows every step; clicking one opens its settings beside the canvas', async () => {
  serve();
  builder(workflow([trigger, node('delay_1', 'delay', 'Wait a bit', { seconds: 5 })], [edge('trigger_1', 'delay_1')]));
  expect(await screen.findByText('Wait a bit')).toBeInTheDocument();
  fireEvent.click(screen.getByText('Wait a bit'));
  const panel = screen.getByRole('region', { name: 'Step settings' });
  expect(within(panel).getByLabelText('Step name')).toHaveValue('Wait a bit');
});

test('+ after a step adds a connected step, and Save keeps positions and connections', async () => {
  serve();
  const onSave = builder(workflow([trigger], []));
  fireEvent.click(await screen.findByRole('button', { name: 'Add a step after Trigger' }));
  fireEvent.click(screen.getByRole('button', { name: /Delay Wait before continuing/ }));
  expect(await screen.findByLabelText('Step name')).toHaveValue('Delay');  // the new step opens
  fireEvent.click(screen.getByRole('button', { name: /Save/ }));
  await waitFor(() => expect(onSave).toHaveBeenCalled());
  const saved = onSave.mock.calls[0][0];
  expect(saved.nodes.map(n => n.id)).toEqual(['trigger_1', 'delay_1']);
  expect(saved.edges).toEqual([expect.objectContaining({ source: 'trigger_1', target: 'delay_1' })]);
  expect(saved.nodes.every(n => n.position)).toBe(true);
});

test('shapes the list cannot show are still editable on the canvas', async () => {
  serve();
  builder(workflow([trigger, node('a', 'delay', 'First'), node('b', 'delay', 'Second')],
    [edge('trigger_1', 'a'), edge('trigger_1', 'b')]));  // two steps start at once
  expect(await screen.findByText('First')).toBeInTheDocument();
  expect(screen.getByText('Second')).toBeInTheDocument();
  expect(screen.getByRole('radio', { name: 'List' })).toBeDisabled();
  expect(screen.getByRole('button', { name: /Save/ })).toBeEnabled();
});

test('conditions offer a yes and a no output', async () => {
  serve();
  builder(workflow([trigger, node('condition_1', 'condition', 'Is it late?', { field: 'x', operator: 'truthy' })], [edge('trigger_1', 'condition_1')]));
  expect(await screen.findByRole('button', { name: 'Add a step if yes after Is it late?' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Add a step if no after Is it late?' })).toBeInTheDocument();
  // Connected outputs don't offer +: the trigger already leads to the condition.
  expect(screen.queryByRole('button', { name: 'Add a step after Trigger' })).toBeNull();
});

test('the read-only canvas shows the steps without editing controls', async () => {
  render(<FlowEditor graph={{ nodes: [trigger, node('d', 'delay', 'Wait')], edges: [edge('trigger_1', 'd')] }} />);
  expect(await screen.findByText('Wait')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Add a step/ })).toBeNull();
});
