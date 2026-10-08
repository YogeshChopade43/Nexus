import type { WorkflowEdge, WorkflowNode } from '../../types/workflow';
import { NODE_ICONS } from './WorkflowBuilder';

const W = 168;
const H = 46;
const GAP_X = 32;
const GAP_Y = 56;

export interface Placed {
  node: WorkflowNode;
  depth: number;
  x: number;
  y: number;
}

/** Rows by longest path from a start step; steps in a row are centred. */
export function layoutGraph(nodes: WorkflowNode[], edges: WorkflowEdge[]): { placed: Placed[]; width: number; height: number } {
  const depth = new Map(nodes.map(n => [n.id, 0]));
  // Longest-path relaxation; capped so an (invalid) cycle can't loop forever.
  for (let round = 0; round < nodes.length; round++) {
    let changed = false;
    for (const edge of edges) {
      const next = (depth.get(edge.source) ?? 0) + 1;
      if (depth.has(edge.target) && next > (depth.get(edge.target) ?? 0)) {
        depth.set(edge.target, next);
        changed = true;
      }
    }
    if (!changed) break;
  }
  const rows: WorkflowNode[][] = [];
  for (const node of nodes) (rows[depth.get(node.id) ?? 0] ??= []).push(node);
  const widest = Math.max(1, ...rows.map(r => r?.length ?? 0));
  const width = widest * W + (widest - 1) * GAP_X;
  const placed = rows.flatMap((row = [], d) => {
    const rowWidth = row.length * W + (row.length - 1) * GAP_X;
    return row.map((node, i) => ({ node, depth: d, x: (width - rowWidth) / 2 + i * (W + GAP_X), y: d * (H + GAP_Y) }));
  });
  return { placed, width, height: rows.length * H + Math.max(0, rows.length - 1) * GAP_Y };
}

function nestedCount(node: WorkflowNode): number {
  const config = (node.config ?? {}) as { body?: { nodes?: unknown[] }; branches?: { nodes?: unknown[] }[] };
  return (config.body?.nodes?.length ?? 0) + (config.branches ?? []).reduce((sum, b) => sum + (b.nodes?.length ?? 0), 0);
}

/** Read-only picture of the workflow graph; the step list stays the accessible source. */
export function WorkflowCanvas({ nodes, edges }: { nodes: WorkflowNode[]; edges: WorkflowEdge[] }) {
  if (nodes.length === 0) return <p className="text-sm text-nexus-text-muted">No steps yet.</p>;
  const { placed, width, height } = layoutGraph(nodes, edges);
  const at = new Map(placed.map(p => [p.node.id, p]));
  const pad = 8;
  return (
    <div className="overflow-auto max-h-[28rem] rounded-lg border border-nexus-border bg-nexus-bg-tertiary/30">
      <svg
        width={width + pad * 2}
        height={height + pad * 2}
        viewBox={`${-pad} ${-pad} ${width + pad * 2} ${height + pad * 2}`}
        role="img"
        aria-label={`Workflow diagram with ${nodes.length} steps`}
        className="mx-auto block"
      >
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="fill-nexus-text-muted" />
          </marker>
        </defs>
        {edges.map(edge => {
          const from = at.get(edge.source);
          const to = at.get(edge.target);
          if (!from || !to) return null;
          const x1 = from.x + W / 2, y1 = from.y + H, x2 = to.x + W / 2, y2 = to.y;
          const mid = (y1 + y2) / 2;
          const label = edge.sourceHandle === 'true' ? 'yes' : edge.sourceHandle === 'false' ? 'no' : edge.condition;
          return (
            <g key={edge.id}>
              <path d={`M${x1},${y1} C${x1},${mid} ${x2},${mid} ${x2},${y2 - 2}`} fill="none" className="stroke-nexus-text-muted" strokeWidth={1.5} markerEnd="url(#arrow)" />
              {label && <text x={(x1 + x2) / 2 + 4} y={mid} className="fill-nexus-text-secondary text-[10px]">{label}</text>}
            </g>
          );
        })}
        {placed.map(({ node, x, y }) => {
          const inner = nestedCount(node);
          return (
            <g key={node.id} transform={`translate(${x},${y})`}>
              <title>{`${node.name} (${node.type})`}</title>
              <rect width={W} height={H} rx={10} className="fill-nexus-bg-secondary stroke-nexus-border" strokeWidth={1.5} />
              <text x={12} y={inner ? 20 : 28} className="fill-nexus-text text-[12px]">
                {`${NODE_ICONS[node.type] ?? '⚙️'} ${node.name.length > 18 ? `${node.name.slice(0, 17)}…` : node.name}`}
              </text>
              {inner > 0 && <text x={12} y={36} className="fill-nexus-text-muted text-[10px]">{inner} step(s) inside</text>}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
