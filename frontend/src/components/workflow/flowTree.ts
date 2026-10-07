// Converts between the stored workflow graph (nodes + edges) and the tree the vertical
// builder edits: a trigger, then steps, where a condition holds "yes" and "no" step lists.
import type { WorkflowEdge, WorkflowNode } from '../../types/workflow';

export type FlowStep =
  | { kind: 'step'; node: WorkflowNode }
  | { kind: 'condition'; node: WorkflowNode; yes: FlowStep[]; no: FlowStep[] };

export interface FlowTree {
  trigger: WorkflowNode | null;
  steps: FlowStep[];
}

type Exit = { source: string; handle?: 'true' | 'false' };

export function treeToGraph(tree: FlowTree): { nodes: WorkflowNode[]; edges: WorkflowEdge[] } {
  const nodes: WorkflowNode[] = [];
  const edges: WorkflowEdge[] = [];

  const connect = (entries: Exit[], target: string) => {
    for (const { source, handle } of entries) {
      edges.push({
        id: `edge-${source}-${target}${handle ? `-${handle}` : ''}`,
        source,
        target,
        ...(handle ? { sourceHandle: handle } : {}),
      });
    }
  };

  // Emits a step list after `entries`; returns the open ends the next step attaches to.
  const emit = (steps: FlowStep[], entries: Exit[]): Exit[] => {
    let open = entries;
    for (const step of steps) {
      nodes.push(step.node);
      connect(open, step.node.id);
      if (step.kind === 'step') {
        open = [{ source: step.node.id }];
      } else {
        const id = step.node.id;
        open = [
          ...emit(step.yes, [{ source: id, handle: 'true' }]),
          ...emit(step.no, [{ source: id, handle: 'false' }]),
        ];
      }
    }
    return open;
  };

  if (tree.trigger) nodes.push(tree.trigger);
  emit(tree.steps, tree.trigger ? [{ source: tree.trigger.id }] : []);
  return { nodes, edges };
}

function branchOf(edge: WorkflowEdge): 'true' | 'false' {
  const label = String(edge.sourceHandle ?? edge.condition ?? 'true').toLowerCase();
  return ['false', 'else', 'no'].includes(label) ? 'false' : 'true';
}

/** The tree for a graph, or null when the graph has a shape the vertical builder can't show. */
export function graphToTree(nodes: WorkflowNode[], edges: WorkflowEdge[]): FlowTree | null {
  const byId = new Map(nodes.map(node => [node.id, node]));
  if (byId.size !== nodes.length) return null;
  if (edges.some(e => !byId.has(e.source) || !byId.has(e.target) || e.source === e.target)) return null;

  const outgoing = new Map<string, WorkflowEdge[]>(nodes.map(node => [node.id, []]));
  const incoming = new Map<string, number>(nodes.map(node => [node.id, 0]));
  for (const edge of edges) {
    outgoing.get(edge.source)!.push(edge);
    incoming.set(edge.target, incoming.get(edge.target)! + 1);
  }

  const triggers = nodes.filter(node => node.type === 'trigger');
  if (triggers.length > 1) return null;
  const trigger = triggers[0] ?? null;

  let start: string | null;
  if (trigger) {
    const outs = outgoing.get(trigger.id)!;
    if (outs.length > 1 || incoming.get(trigger.id)) return null;
    start = outs[0]?.target ?? null;
  } else {
    const roots = nodes.filter(node => !incoming.get(node.id));
    if (roots.length > 1 || (nodes.length > 0 && roots.length === 0)) return null;
    start = roots[0]?.id ?? null;
  }

  const reachable = (from: string | null): string[] => {
    const order: string[] = [];
    const seen = new Set<string>();
    const queue = from ? [from] : [];
    while (queue.length) {
      const id = queue.shift()!;
      if (seen.has(id)) continue;
      seen.add(id);
      order.push(id);
      for (const edge of outgoing.get(id)!) queue.push(edge.target);
    }
    return order;
  };

  const visited = new Set<string>();

  const walk = (from: string | null, stopAt: string | null): FlowStep[] | null => {
    const steps: FlowStep[] = [];
    let current = from;
    while (current && current !== stopAt) {
      if (visited.has(current)) return null; // cycle, or a node reached two ways outside a join
      visited.add(current);
      const node = byId.get(current)!;
      if (node.type === 'trigger') return null;
      const outs = outgoing.get(current)!;

      if (node.type !== 'condition') {
        if (outs.length > 1) return null;
        steps.push({ kind: 'step', node });
        current = outs[0]?.target ?? null;
        continue;
      }

      const yesEdges = outs.filter(e => branchOf(e) === 'true');
      const noEdges = outs.filter(e => branchOf(e) === 'false');
      if (yesEdges.length > 1 || noEdges.length > 1) return null;
      const yesHead = yesEdges[0]?.target ?? null;
      const noHead = noEdges[0]?.target ?? null;

      // Where the branches meet again: the earliest node reachable from both heads.
      const fromNo = new Set(reachable(noHead));
      const shared = reachable(yesHead).filter(id => fromNo.has(id));
      const join = shared.find(candidate => !shared.some(other => other !== candidate && reachable(other).includes(candidate))) ?? null;

      const yes = walk(yesHead, join ?? stopAt);
      const no = walk(noHead, join ?? stopAt);
      if (!yes || !no) return null;
      steps.push({ kind: 'condition', node, yes, no });
      current = join;
    }
    return steps;
  };

  const steps = walk(start, null);
  if (!steps) return null;
  // Every non-trigger node must be part of the tree; otherwise something would be dropped on save.
  if (visited.size !== nodes.length - (trigger ? 1 : 0)) return null;
  return { trigger, steps };
}
