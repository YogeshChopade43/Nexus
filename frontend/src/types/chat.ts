export type MessageRole = 'user' | 'assistant';

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: string;
  events?: AgentEvent[];
  summary?: string;
  status?: string;
  /** Live tool activity while a streamed reply is still running. */
  activity?: ToolActivity[];
  pendingAction?: PendingAction;
}

export interface ToolActivity {
  tool: string;
  state: 'running' | 'ok' | 'failed';
  summary?: string;
}

export interface PendingAction {
  tool: string;
  arguments: Record<string, unknown>;
}

export interface ChatAttachment {
  name: string;
  content: string;
}

export interface AgentRunRequest {
  message: string;
  task?: string;
  context?: Record<string, unknown>;
  available_tools?: string[];
  llm_provider_id?: number;
  session_id?: string;
  attachments?: ChatAttachment[];
}

export interface StoredMessage {
  role: MessageRole;
  content: string;
  events?: AgentEvent[];
  status?: string;
  summary?: string;
}

export interface AgentSession {
  id: number;
  session_id: string;
  title: string;
  messages: StoredMessage[];
  metadata?: { pending?: { state?: { queue?: { name: string; arguments: Record<string, unknown> }[] } } };
  created_at: string;
  updated_at: string;
}

export interface AgentEvent {
  type: string;
  nodeId?: string;
  nodeName?: string;
  data?: unknown;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  error?: string;
  [key: string]: unknown;
}

export interface AgentRunResponse {
  status: string;
  events?: AgentEvent[];
  summary?: string;
  message?: string;
  response?: string;
  session_id?: string | null;
  pending_action?: PendingAction | null;
}

export type AgentStreamEvent =
  | { type: 'tool_call'; tool: string; arguments: Record<string, unknown> }
  | { type: 'tool_result'; tool: string; ok: boolean; summary: string }
  | { type: 'approval_needed'; tool: string; arguments: Record<string, unknown> }
  | { type: 'delta'; text: string }
  | { type: 'error'; error: string }
  | ({ type: 'done' } & AgentRunResponse);

export interface SendMessageRequest {
  content: string;
  attachments?: File[];
}
