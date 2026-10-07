export type MessageRole = 'user' | 'assistant';

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: string;
  events?: AgentEvent[];
  summary?: string;
  status?: string;
}

export interface AgentRunRequest {
  message: string;
  task?: string;
  context?: Record<string, unknown>;
  available_tools?: string[];
  llm_provider_id?: number;
  session_id?: string;
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
}

export interface SendMessageRequest {
  content: string;
  attachments?: File[];
}
