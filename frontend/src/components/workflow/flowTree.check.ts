// Self-check for tree <-> graph conversion. Run: npx tsx src/components/workflow/flowTree.check.ts
import assert from 'node:assert/strict';
import { graphToTree, treeToGraph, type FlowStep, type FlowTree } from './flowTree';
import type { WorkflowNode } from '../../types/workflow';

const n = (id: string, type: WorkflowNode['type'] = 'action'): WorkflowNode => ({ id, type, name: id, config: {} });
const step = (id: string): FlowStep => ({ kind: 'step', node: n(id) });
const cond = (id: string, yes: FlowStep[], no: FlowStep[]): FlowStep => ({ kind: 'condition', node: n(id, 'condition'), yes, no });

function roundTrip(name: string, tree: FlowTree) {
  const { nodes, edges } = treeToGraph(tree);
  assert.deepEqual(graphToTree(nodes, edges), tree, `round trip: ${name}`);
}

const trigger = n('trigger_1', 'trigger');

roundTrip('linear', { trigger, steps: [step('a'), step('b'), step('c')] });
roundTrip('condition both branches', { trigger, steps: [step('a'), cond('c', [step('y1'), step('y2')], [step('n1')])] });
roundTrip('condition empty no', { trigger, steps: [cond('c', [step('y1')], [])] });
roundTrip('condition both empty then step', { trigger, steps: [cond('c', [], []), step('after')] });
roundTrip('nested condition', { trigger, steps: [cond('c', [cond('c2', [step('yy')], [step('yn')])], [step('n1')])] });
roundTrip('steps after condition (join)', { trigger, steps: [cond('c', [step('y1')], [step('n1')]), step('after'), step('after2')] });
roundTrip('nested condition then join', { trigger, steps: [cond('c', [cond('c2', [step('yy')], [])], [step('n1')]), step('after')] });
roundTrip('trigger only', { trigger, steps: [] });
roundTrip('no trigger', { trigger: null, steps: [step('a'), step('b')] });

// Graphs the vertical builder cannot show must be refused, never silently reshaped.
assert.equal(
  graphToTree([n('a'), n('b'), n('c')], [
    { id: 'e1', source: 'a', target: 'b' },
    { id: 'e2', source: 'a', target: 'c' },
  ]),
  null,
  'two plain outgoing edges',
);
assert.equal(
  graphToTree([n('a'), n('b')], [
    { id: 'e1', source: 'a', target: 'b' },
    { id: 'e2', source: 'b', target: 'a' },
  ]),
  null,
  'cycle',
);

console.log('flowTree checks passed');
