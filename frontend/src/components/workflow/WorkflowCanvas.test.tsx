import { expect, test } from 'vitest';
import { render, screen } from '@testing-library/react';
import { WorkflowCanvas, layoutGraph } from './WorkflowCanvas';
import type { WorkflowEdge, WorkflowNode } from '../../types/workflow';

const n = (id: string, type: WorkflowNode['type'] = 'action'): WorkflowNode => ({ id, type, name: id, config: {} });
const e = (source: string, target: string, sourceHandle?: string): WorkflowEdge => ({ id: `${source}-${target}`, source, target, sourceHandle });

test('rows follow the longest path, so a join sits below both branches', () => {
  const nodes = [n('t', 'trigger'), n('if', 'condition'), n('yes'), n('no'), n('join')];
  const edges = [e('t', 'if'), e('if', 'yes', 'true'), e('if', 'no', 'false'), e('yes', 'join'), e('no', 'join'), e('t', 'join')];
  const depth = Object.fromEntries(layoutGraph(nodes, edges).placed.map(p => [p.node.id, p.depth]));
  expect(depth).toEqual({ t: 0, if: 1, yes: 2, no: 2, join: 3 });
});

test('a cycle does not hang the layout', () => {
  expect(layoutGraph([n('a'), n('b')], [e('a', 'b'), e('b', 'a')]).placed).toHaveLength(2);
});

test('draws every step and labels condition branches', () => {
  render(<WorkflowCanvas nodes={[n('if', 'condition'), n('ok')]} edges={[e('if', 'ok', 'true')]} />);
  expect(screen.getByRole('img', { name: 'Workflow diagram with 2 steps' })).toBeInTheDocument();
  expect(screen.getByText('yes')).toBeInTheDocument();
});
