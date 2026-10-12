import { Fragment, useMemo, useState, type ReactNode } from 'react';
import {
  Background, Controls, Handle, Panel, Position, ReactFlow,
  type Connection, type Edge, type Node, type NodeChange, type NodeProps, type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { LayoutGrid, Plus, Trash2, X, Zap } from 'lucide-react';
import { cn } from '../../lib/utils';
import { ActionPicker, type PickedAction } from './ActionPicker';
import { NODE_H, NODE_W, connect, earlierSteps, layout, removeNodes, wouldCycle, type Graph } from './graphEdit';
import { NestedSections, StepDetails, stepSummary, type BuilderContext } from './WorkflowBuilder';
import { NodeTile } from './NodeTile';
import { defaultTriggerConfig, triggerSummary } from './TriggerCard';
import type { WorkflowNode } from '../../types/workflow';

interface StepData extends Record<string, unknown> {
  node: WorkflowNode;
  summary: string;
  editable: boolean;
  /** Outputs already connected (null: the plain output); + shows only on free ones, as in n8n. */
  used: Array<string | null>;
  onAdd: (handle?: 'true' | 'false') => void;
}

const HANDLE = '!w-2.5 !h-2.5 !border-2 !border-nexus-bg-secondary !bg-nexus-accent';

function AddButton({ top, label, onClick }: { top: number; label: string; onClick: () => void }) {
  return (
    <button type="button" aria-label={label} title={label}
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      style={{ top: `${top}%` }}
      className="nodrag nopan absolute -right-11 -translate-y-1/2 w-6 h-6 rounded-full border border-nexus-border bg-nexus-bg-secondary text-nexus-text-secondary hover:text-nexus-accent-text hover:border-nexus-accent flex items-center justify-center">
      <Plus className="w-3.5 h-3.5" />
    </button>
  );
}

/** One step on the canvas: icon, name, what it does; an input on the left, outputs (yes/no for a condition) on the right. */
function StepNode({ data, selected }: NodeProps<Node<StepData>>) {
  const { node, summary, editable, used, onAdd } = data;
  return (
    <div style={{ width: NODE_W, minHeight: NODE_H }}
      className={cn('relative rounded-lg border bg-nexus-bg-secondary px-3 py-2 shadow-sm',
        selected ? 'border-nexus-accent ring-2 ring-nexus-accent/30' : 'border-nexus-border')}>
      {node.type !== 'trigger' && <Handle type="target" position={Position.Left} className={HANDLE} />}
      <div className="flex items-center gap-2 min-w-0">
        <NodeTile type={node.type} />
        <span className="text-sm font-medium text-nexus-text truncate">{node.name}</span>
      </div>
      {summary && <p className="text-xs text-nexus-text-muted truncate mt-0.5">{summary}</p>}
      {node.type === 'condition' ? (['true', 'false'] as const).map((handle, i) => {
        const top = i ? 72 : 28;
        const word = handle === 'true' ? 'yes' : 'no';
        return (
          <Fragment key={handle}>
            <Handle id={handle} type="source" position={Position.Right} style={{ top: `${top}%` }} className={HANDLE} />
            <span className={cn('absolute -right-7 text-[10px] font-medium', handle === 'true' ? 'text-green-500' : 'text-red-500')}
              style={{ top: `calc(${top}% - 16px)` }}>{word}</span>
            {editable && !used.includes(handle) && <AddButton top={top} label={`Add a step if ${word} after ${node.name}`} onClick={() => onAdd(handle)} />}
          </Fragment>
        );
      }) : (
        <>
          <Handle type="source" position={Position.Right} className={HANDLE} />
          {editable && !used.length && <AddButton top={50} label={`Add a step after ${node.name}`} onClick={() => onAdd()} />}
        </>
      )}
    </div>
  );
}

const NODE_TYPES = { step: StepNode };

interface FlowEditorProps {
  graph: Graph;
  /** Without it the canvas is a read-only picture. */
  onChange?: (graph: Graph) => void;
  /** What the step settings panel needs (tools, servers, tests…); required for editing. */
  ctx?: BuilderContext;
  renderTrigger?: (node: WorkflowNode, update: (node: WorkflowNode) => void) => ReactNode;
}

/** The workflow as a node graph, n8n-style: drag steps, connect outputs to inputs, + to add the next step,
 *  click a step to edit it in the panel beside the canvas. */
export function FlowEditor({ graph, onChange, ctx, renderTrigger }: FlowEditorProps) {
  const editable = Boolean(onChange && ctx);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [adding, setAdding] = useState<{ source: string | null; handle?: 'true' | 'false' } | null>(null);
  const [flow, setFlow] = useState<ReactFlowInstance<Node<StepData>, Edge> | null>(null);
  // Sizes React Flow measured. They must be handed back with each node: a node given without them is reset and
  // waits to be measured again, which never happens if its size didn't change, so its lines vanish.
  const [measured, setMeasured] = useState<Record<string, { width: number; height: number }>>({});

  const nodes = useMemo(() => layout(graph.nodes, graph.edges), [graph]);  // fills in positions not yet set
  const { edges } = graph;
  const change = (next: Graph) => onChange?.(next);

  const rfNodes: Node<StepData>[] = nodes.map(node => ({
    id: node.id, type: 'step', position: node.position!, initialWidth: NODE_W, initialHeight: NODE_H, measured: measured[node.id], selected: node.id === selectedId, deletable: editable,
    data: {
      node, editable,
      used: edges.filter(edge => edge.source === node.id).map(edge => edge.sourceHandle ?? null),
      summary: node.type === 'trigger' ? triggerSummary(node.config) : ctx ? stepSummary(node, ctx.servers) : '',
      onAdd: (handle) => { setSelectedId(null); setAdding({ source: node.id, handle }); },
    },
  }));
  const rfEdges: Edge[] = edges.map(edge => ({
    id: edge.id, source: edge.source, target: edge.target, sourceHandle: edge.sourceHandle ?? null,
    selected: edge.id === selectedEdge, deletable: editable,
  }));

  const onNodesChange = (changes: NodeChange<Node<StepData>>[]) => {
    const sized = changes.flatMap(c => (c.type === 'dimensions' && c.dimensions ? [[c.id, c.dimensions] as const] : []));
    if (sized.length) setMeasured(prev => ({ ...prev, ...Object.fromEntries(sized) }));
    const moved = new Map(changes.flatMap(c => (c.type === 'position' && c.position ? [[c.id, c.position] as const] : [])));
    if (moved.size) change({ nodes: nodes.map(node => (moved.has(node.id) ? { ...node, position: moved.get(node.id)! } : node)), edges });
  };

  const isValidConnection = (link: Connection | Edge) =>
    link.source !== link.target && nodes.find(n => n.id === link.target)?.type !== 'trigger'
    && !wouldCycle(edges, link.source, link.target);

  const add = (picked: PickedAction) => {
    if (!ctx || !adding) return;
    const fresh = ctx.newNode(picked);
    const source = nodes.find(node => node.id === adding.source);
    const siblings = source ? edges.filter(edge => edge.source === source.id).length : 0;
    const position = source
      ? { x: source.position!.x + NODE_W + 80, y: source.position!.y + siblings * (NODE_H + 40) }
      : { x: Math.max(0, ...nodes.map(n => n.position!.x)) + NODE_W + 80, y: 0 };
    change({
      nodes: [...nodes, { ...fresh, position }],
      edges: source ? connect(edges, { source: source.id, target: fresh.id, sourceHandle: adding.handle }) : edges,
    });
    setAdding(null);
    setSelectedId(fresh.id);
    // Bring the new step into view (it is often placed beyond the right edge).
    flow?.setCenter(position.x + NODE_W / 2, position.y + NODE_H / 2, { zoom: flow.getZoom(), duration: 200 });
  };

  const selected = nodes.find(node => node.id === selectedId) ?? null;
  const update = (next: WorkflowNode) => change({ nodes: nodes.map(node => (node.id === next.id ? next : node)), edges });
  const trigger = nodes.find(node => node.type === 'trigger') ?? null;
  const dark = typeof document !== 'undefined' && !document.documentElement.classList.contains('light');

  return (
    <div className="flex flex-col lg:flex-row gap-3">
      <div className={cn('relative flex-1 rounded-lg border border-nexus-border bg-nexus-bg-tertiary/30', editable ? 'h-[60vh] min-h-[360px]' : 'h-80')}>
        <ReactFlow
          nodes={rfNodes} edges={rfEdges} nodeTypes={NODE_TYPES} colorMode={dark ? 'dark' : 'light'} fitView
          fitViewOptions={{ maxZoom: 1, padding: editable ? 0.35 : 0.08 }} minZoom={0.2}
          nodesDraggable={editable} nodesConnectable={editable} elementsSelectable={editable}
          zoomOnScroll={editable} preventScrolling={editable} deleteKeyCode={editable ? ['Backspace', 'Delete'] : null}
          onInit={setFlow}
          onNodesChange={onNodesChange}
          onNodeClick={(_, node) => { setAdding(null); setSelectedEdge(null); setSelectedId(node.id); }}
          onEdgeClick={(_, edge) => { setSelectedId(null); setSelectedEdge(edge.id); }}
          onPaneClick={() => { setSelectedId(null); setSelectedEdge(null); }}
          onConnect={(link) => change({ nodes, edges: connect(edges, link) })}
          isValidConnection={isValidConnection}
          onDelete={({ nodes: gone, edges: cut }) => {
            const cutIds = new Set(cut.map(edge => edge.id));
            const next = removeNodes({ nodes, edges: edges.filter(edge => !cutIds.has(edge.id)) }, gone.map(node => node.id));
            if (gone.some(node => node.id === selectedId)) setSelectedId(null);
            change(next);
          }}
        >
          <Background gap={20} />
          <Controls showInteractive={false} />
          {editable && (
            <Panel position="top-left" className="flex gap-2">
              {!trigger && (
                <button type="button" onClick={() => change({ nodes: [{ id: 'trigger_1', type: 'trigger', name: 'Trigger', config: defaultTriggerConfig('manual') }, ...nodes], edges })}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-lg border border-nexus-border bg-nexus-bg-secondary text-xs text-nexus-accent-text"><Zap className="h-3.5 w-3.5" /> Add trigger</button>
              )}
              <button type="button" onClick={() => { setSelectedId(null); setAdding({ source: null }); }}
                className="flex items-center gap-1 px-2.5 py-1 rounded-lg border border-nexus-border bg-nexus-bg-secondary text-xs text-nexus-text-secondary hover:text-nexus-accent-text">
                <Plus className="w-3.5 h-3.5" /> Add step
              </button>
              <button type="button" onClick={() => change({ nodes: layout(nodes, edges, true), edges })}
                className="flex items-center gap-1 px-2.5 py-1 rounded-lg border border-nexus-border bg-nexus-bg-secondary text-xs text-nexus-text-secondary hover:text-nexus-accent-text">
                <LayoutGrid className="w-3.5 h-3.5" /> Tidy up
              </button>
            </Panel>
          )}
        </ReactFlow>
      </div>

      {editable && ctx && adding && (
        <section aria-label="Add a step" className="w-full lg:w-[420px] shrink-0 max-h-[60vh] overflow-y-auto">
          <ActionPicker servers={ctx.servers} onPick={add} onClose={() => setAdding(null)} />
        </section>
      )}

      {editable && ctx && selected && !adding && (
        <section aria-label="Step settings"
          className="w-full lg:w-[420px] shrink-0 max-h-[60vh] overflow-y-auto rounded-lg border border-nexus-border bg-nexus-bg-secondary p-3 space-y-3">
          <div className="flex items-center gap-2">
            <NodeTile type={selected.type} />
            <input value={selected.name} onChange={(e) => update({ ...selected, name: e.target.value })} aria-label="Step name"
              className="flex-1 min-w-0 bg-transparent text-sm font-medium text-nexus-text focus:outline-none" />
            <button type="button" aria-label="Delete step" className="text-nexus-text-muted hover:text-nexus-danger"
              onClick={() => { setSelectedId(null); change(removeNodes({ nodes, edges }, [selected.id])); }}>
              <Trash2 className="w-4 h-4" />
            </button>
            <button type="button" aria-label="Close settings" className="text-nexus-text-muted hover:text-nexus-text" onClick={() => setSelectedId(null)}>
              <X className="w-4 h-4" />
            </button>
          </div>
          {selected.type === 'trigger' ? renderTrigger?.(selected, update) : (
            <>
              <StepDetails node={selected} ctx={ctx}
                onConfig={(patch) => update({ ...selected, config: { ...selected.config, ...patch } })}
                sources={{ trigger, earlierSteps: earlierSteps(nodes, edges, selected.id), lastOutputs: ctx.lastOutputs, scopes: [] }} />
              <NestedSections node={selected} ctx={ctx} earlier={earlierSteps(nodes, edges, selected.id)} listKey={`canvas/${selected.id}`} scopes={[]}
                onConfig={(patch) => update({ ...selected, config: { ...selected.config, ...patch } })} />
            </>
          )}
        </section>
      )}

      {editable && !adding && !selected && (
        <section aria-label="Step settings" className="w-full lg:w-[420px] shrink-0 rounded-lg border border-dashed border-nexus-border p-4 text-sm text-nexus-text-muted">
          Click a step to change its settings, or use + to add the next one.
        </section>
      )}
    </div>
  );
}
