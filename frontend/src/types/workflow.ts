export type WorkflowId = number | string;

export type WorkflowNodeType = 'trigger' | 'action' | 'llm' | 'condition' | 'transform' | 'delay' | 'output'
  | 'http' | 'code' | 'workflow' | 'loop' | 'parallel';

/** A sub-workflow held inside a step: loop body, parallel branch or error handler. */
export interface NestedGraph {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

export interface WorkflowNode {
  id: string;
  type: WorkflowNodeType;
  name: string;
  description?: string;
  position?: { x: number; y: number };
  config: Record<string, unknown>;
  inputs?: NodePort[];
  outputs?: NodePort[];
  app_id?: string;
}

export type TriggerType = 'manual' | 'recurrence' | 'poll' | 'schedule' | 'webhook' | 'app_event';
export type Frequency = 'minute' | 'hour' | 'day' | 'week' | 'month';
export type Weekday = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun';

export interface ManualInput {
  name: string;
  type: 'text' | 'number' | 'boolean';
  required: boolean;
  default?: string | number | boolean | null;
}

export interface RecurrenceSettings {
  frequency: Frequency;
  interval: number;
  at: string;
  weekdays: Weekday[];
  month_day: number | null;
  timezone: string;
}

export interface TriggerConfig {
  type: TriggerType;
  schedule?: string | null;
  timezone?: string;
  app_id?: string | null;
  event?: string | null;
  webhook_path?: string;
  next_run_at?: string | null;
  inputs?: ManualInput[];
  frequency?: Frequency | null;
  interval?: number;
  at?: string;
  weekdays?: Weekday[];
  month_day?: number | null;
  tool?: string | null;
  parameters?: Record<string, unknown>;
  interval_minutes?: number;
  items_path?: string;
  id_field?: string;
  concurrency?: number;
}

export interface AppWebhookSetup {
  app_id: string;
  label: string;
  secret_env: string;
  path: string;
  configured: boolean;
  steps: string[];
}

export interface TriggerStatus {
  last_checked_at: string | null;
  last_error: string | null;
}

export interface TriggerTypeInfo {
  id: string;
  label: string;
  app_id: string | null;
  events: string[];
  description: string;
}

/** JSON Schema for a tool's inputs, as the MCP server sends it (may use $defs, anyOf, enum, …). */
export interface ToolParameterSchema {
  type: 'object';
  properties: Record<string, Record<string, unknown> & { type?: string | string[]; description?: string }>;
  required?: string[];
  $defs?: Record<string, Record<string, unknown>>;
}

export interface ToolDefinition {
  tool_name: string;
  app_id: string;
  description: string;
  available: boolean;
  parameters: ToolParameterSchema;
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
  sourceHandle?: string;
  target: string;
  targetHandle?: string;
  type?: 'default' | 'conditional';
  condition?: string;
}

export interface Workflow {
  id: WorkflowId;
  name: string;
  description: string;
  /** Folder it's grouped in ('' or missing = none). */
  folder?: string;
  steps: Record<string, unknown>[];
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  version: number;
  isActive: boolean;
  enabled: boolean;
  trigger: string;
  trigger_config?: TriggerConfig;
  trigger_status?: TriggerStatus | null;
  last_status?: ExecutionStatus | null;
  llm_provider_id?: number | null;
  warnings?: string[];
  last_run?: string | null;
  createdAt?: string;
  updatedAt?: string;
  createdBy?: string;
}

export type ExecutionStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'partial' | 'skipped';

export interface WorkflowVersion {
  version: number;
  name: string;
  saved_at: string;
  steps: number;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  /** What to connect first ("Email", "Web search"); empty when it works as is. */
  needs?: string[];
}

export interface WorkflowDraft {
  name: string;
  description: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  warnings?: string[];
}

export interface StepTestResult {
  status: 'success' | 'failed';
  output?: unknown;
  error?: string;
  duration_ms: number;
}

export interface ExecutionTraceEntry {
  id: string;
  nodeId: string;
  nodeName: string;
  type: string;
  reason?: string;
  attempts?: number;
  parent?: string;
  reused?: boolean;
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
  run_id?: string | null;
  status?: ExecutionStatus | null;
  steps: ExecutionTraceEntry[];
  last_run?: string;
}

export interface WorkflowCreateRequest {
  name: string;
  description: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  steps?: Record<string, unknown>[];
  isActive?: boolean;
  enabled?: boolean;
  trigger?: string;
  llm_provider_id?: number | null;
}

export interface WorkflowUpdateRequest {
  id: WorkflowId;
  name?: string;
  description?: string;
  nodes?: WorkflowNode[];
  edges?: WorkflowEdge[];
  steps?: Record<string, unknown>[];
  isActive?: boolean;
  enabled?: boolean;
  trigger?: string;
  llm_provider_id?: number | null;
  folder?: string;
}

export interface WorkflowRunRequest {
  input_data?: Record<string, unknown>;
  /** Running the digital will by hand: yes, really send everything. */
  confirm?: boolean;
}
