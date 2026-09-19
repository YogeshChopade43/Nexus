export type WorkflowId = number | string;

export interface WorkflowNode {
  id: string;
  type: 'trigger' | 'action' | 'condition' | 'transform' | 'output';
  name: string;
  description: string;
  position: { x: number; y: number };
  config: Record<string, unknown>;
  inputs: NodePort[];
  outputs: NodePort[];
  app_id?: string;
}

export interface NodePort {
  id: string;
  name: string;
  type: string;
  required: boolean;
  description: string;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  sourceHandle: string;
  target: string;
  targetHandle: string;
  type?: 'default' | 'conditional';
  condition?: string;
}

export interface Workflow {
  id: WorkflowId;
  name: string;
  description: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  version: number;
  isActive: boolean;
  createdAt?: string;
  updatedAt?: string;
  createdBy?: string;
}

export type ExecutionStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'partial' | 'skipped';

export interface ExecutionTraceEntry {
  id: string;
  nodeId: string;
  nodeName: string;
  type: 'start' | 'complete' | 'error' | 'conditional' | 'tool_executed';
  timestamp: string;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  parameters?: Record<string, unknown>;
  data?: Record<string, unknown>;
  error?: string;
  duration?: number;
  step?: number;
  tool?: string;
  tool_name?: string;
  app_id?: string;
  connected?: boolean;
  status?: string;
}

export interface WorkflowExecution {
  id: string;
  workflowId: WorkflowId;
  workflow_id?: WorkflowId;
  status: ExecutionStatus;
  startedAt: string;
  started_at?: string;
  completedAt?: string;
  completed_at?: string;
  input?: Record<string, unknown>;
  input_data?: Record<string, unknown>;
  output?: Record<string, unknown>;
  error?: string;
  events?: ExecutionTraceEntry[];
  trace?: ExecutionTraceEntry[];
}

export interface WorkflowRunsResponse {
  workflow_id: WorkflowId;
  workflowId: WorkflowId;
  name?: string;
  last_run?: string;
  runs: WorkflowExecution[];
}

export interface WorkflowTraceResponse {
  workflow_id: WorkflowId;
  workflowId: WorkflowId;
  steps: ExecutionTraceEntry[];
  last_run?: string;
}

export interface WorkflowCreateRequest {
  name: string;
  description: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  isActive?: boolean;
}

export interface WorkflowUpdateRequest {
  id: WorkflowId;
  name?: string;
  description?: string;
  nodes?: WorkflowNode[];
  edges?: WorkflowEdge[];
  isActive?: boolean;
}

export interface WorkflowRunRequest {
  input_data?: Record<string, unknown>;
}
