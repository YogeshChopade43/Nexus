import { expect, test } from 'vitest';
import { connect, earlierSteps, layout, removeNodes, wouldCycle } from './graphEdit';
import type { WorkflowEdge, WorkflowNode } from '../../types/workflow';

const n = (id: string, type: WorkflowNode['type'] = 'action', position?: WorkflowNode['position']): WorkflowNode =>
  ({ id, type, name: id, config: {}, ...(position ? { position } : {}) });
const e = (source: string, target: string, sourceHandle?: string): WorkflowEdge =>
  ({ id: `${source}-${target}`, source, target, ...(sourceHandle ? { sourceHandle } : {}) });

test('layout runs left to right by longest path, and keeps positions people dragged', () => {
  const nodes = [n('t', 'trigger'), n('if', 'condition'), n('yes'), n('no'), n('join', 'action', { x: 999, y: 5 })];
  const edges = [e('t', 'if'), e('if', 'yes', 'true'), e('if', 'no', 'false'), e('yes', 'join'), e('no', 'join')];
  const placed = Object.fromEntries(layout(nodes, edges).map(node => [node.id, node.position!]));
  expect(placed.t.x).toBeLessThan(placed.if.x);
  expect(placed.if.x).toBeLessThan(placed.yes.x);
  expect(placed.yes.x).toBe(placed.no.x);
  expect(placed.yes.y).not.toBe(placed.no.y);
  expect(placed.join).toEqual({ x: 999, y: 5 });
  // "Tidy up" re-places everything, dragged or not.
  expect(layout(nodes, edges, true).find(node => node.id === 'join')!.position!.x).toBeGreaterThan(placed.yes.x);
});

test('a connection that would make a loop is refused; one per condition branch', () => {
  const edges = [e('a', 'b'), e('b', 'c')];
  expect(wouldCycle(edges, 'c', 'a')).toBe(true);
  expect(wouldCycle(edges, 'a', 'a')).toBe(true);
  expect(wouldCycle(edges, 'a', 'c')).toBe(false);
  expect(connect(edges, { source: 'c', target: 'a' })).toBe(edges);  // unchanged
  const linked = connect(edges, { source: 'a', target: 'c' });
  expect(linked).toHaveLength(3);
  expect(connect(linked, { source: 'a', target: 'c' })).toBe(linked);  // no duplicates
  // A condition's "yes" goes to one place: reconnecting it moves the edge.
  const branched = connect([e('if', 'x', 'true')], { source: 'if', target: 'y', sourceHandle: 'true' });
  expect(branched.map(edge => edge.target)).toEqual(['y']);
});

test('removing a step removes its connections', () => {
  const graph = removeNodes({ nodes: [n('a'), n('b'), n('c')], edges: [e('a', 'b'), e('b', 'c')] }, ['b']);
  expect(graph.nodes.map(node => node.id)).toEqual(['a', 'c']);
  expect(graph.edges).toEqual([]);
});

test('earlier steps are everything that runs before a step, in order', () => {
  const nodes = [n('t', 'trigger'), n('a'), n('b'), n('c'), n('other')];
  const edges = [e('t', 'a'), e('a', 'b'), e('t', 'other'), e('b', 'c'), e('other', 'c')];
  expect(earlierSteps(nodes, edges, 'b').map(node => node.id)).toEqual(['a']);
  expect(earlierSteps(nodes, edges, 'c').map(node => node.id).sort()).toEqual(['a', 'b', 'other']);
});
