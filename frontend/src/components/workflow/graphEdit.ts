// Editing the stored workflow graph (nodes + edges) directly, for the drag-and-drop canvas.
import type { WorkflowEdge, WorkflowNode } from '../../types/workflow';

export interface Graph {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

export const NODE_W = 220;
export const NODE_H = 64;
const COL_GAP = 80;
const ROW_GAP = 40;

/** Columns by longest path from a start step (left to right), rows within a column.
 *  Nodes keep a position they already have unless ``all`` ("Tidy up"). */
export function layout(nodes: WorkflowNode[], edges: WorkflowEdge[], all = false): WorkflowNode[] {
  const depth = new Map(nodes.map(node => [node.id, 0]));
  for (let round = 0; round < nodes.length; round++) {  // capped: a cycle can't loop forever
    let changed = false;
    for (const edge of edges) {
      const next = (depth.get(edge.source) ?? 0) + 1;
      if (depth.has(edge.target) && next > depth.get(edge.target)!) {
        depth.set(edge.target, next);
        changed = true;
      }
    }
    if (!changed) break;
  }
  const rows = new Map<number, number>();
  return nodes.map(node => {
    const column = depth.get(node.id) ?? 0;
    const row = rows.get(column) ?? 0;
    rows.set(column, row + 1);
    if (node.position && !all) return node;
    return { ...node, position: { x: column * (NODE_W + COL_GAP), y: row * (NODE_H + ROW_GAP) } };
  });
}

/** Does an edge source -> target close a loop? */
export function wouldCycle(edges: WorkflowEdge[], source: string, target: string): boolean {
  const seen = new Set<string>();
  const stack = [target];
  while (stack.length) {
    const id = stack.pop()!;
    if (id === source) return true;
    if (seen.has(id)) continue;
    seen.add(id);
    for (const edge of edges) if (edge.source === id) stack.push(edge.target);
  }
  return false;
}

/** ``edges`` plus a new connection; unchanged when it would loop or already exists. A condition's
 *  yes/no output leads to one place, so connecting it again moves that branch. */
export function connect(edges: WorkflowEdge[], link: { source: string; target: string; sourceHandle?: string | null }): WorkflowEdge[] {
  const handle = link.sourceHandle ?? undefined;
  if (wouldCycle(edges, link.source, link.target)) return edges;
  if (edges.some(edge => edge.source === link.source && edge.target === link.target && edge.sourceHandle === handle)) return edges;
  const kept = handle ? edges.filter(edge => !(edge.source === link.source && edge.sourceHandle === handle)) : edges;
  return [...kept, {
    id: `edge-${link.source}-${link.target}${handle ? `-${handle}` : ''}`,
    source: link.source, target: link.target, ...(handle ? { sourceHandle: handle } : {}),
  }];
}

export function removeNodes(graph: Graph, ids: string[]): Graph {
  const gone = new Set(ids);
  return {
    nodes: graph.nodes.filter(node => !gone.has(node.id)),
    edges: graph.edges.filter(edge => !gone.has(edge.source) && !gone.has(edge.target)),
  };
}

/** Steps that run before ``id`` (what its settings can refer to), in run order; the trigger is left out. */
export function earlierSteps(nodes: WorkflowNode[], edges: WorkflowEdge[], id: string): WorkflowNode[] {
  const before = new Set<string>();
  const stack = [id];
  while (stack.length) {
    const current = stack.pop()!;
    for (const edge of edges) {
      if (edge.target === current && !before.has(edge.source)) {
        before.add(edge.source);
        stack.push(edge.source);
      }
    }
  }
  const order = layout(nodes, edges, true);  // columns follow run order
  return order
    .filter(node => before.has(node.id) && node.type !== 'trigger')
    .sort((a, b) => a.position!.x - b.position!.x)
    .map(node => nodes.find(original => original.id === node.id)!);
}
