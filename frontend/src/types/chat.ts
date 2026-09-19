export type MessageRole = 'user' | 'assistant';

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: string;
}

export interface AgentRunRequest {
  message: string;
  task?: string;
  context?: Record<string, unknown>;
  available_tools?: string[];
  llm_provider_id?: number;
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
