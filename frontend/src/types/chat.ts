import type { Citation } from './rag';

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
  /** Questions the reply paused to ask (status needs_input). */
  pendingQuestion?: PendingQuestion;
  usage?: ReplyUsage | null;
  /** Document passages the reply cited as [n]. */
  citations?: Citation[] | null;
}

/** Tokens one reply used, and its cost when prices are set on the Dashboard. */
export interface ReplyUsage {
  input_tokens: number;
  output_tokens: number;
  estimated: boolean;
  cost: number | null;
}

/** Per-conversation options, saved with the conversation. */
export interface ChatSettings {
  /** MCP server slugs this chat may use; null = all servers. */
  servers: string[] | null;
  instructions: string;
  temperature: number | null;
  /** Answer from this library: searched automatically for every message. */
  library_id: number | null;
}

export const DEFAULT_CHAT_SETTINGS: ChatSettings = { servers: null, instructions: '', temperature: null, library_id: null };

export interface ToolActivity {
  tool: string;
  state: 'running' | 'ok' | 'failed';
  summary?: string;
}

export interface PendingAction {
  tool: string;
  arguments: Record<string, unknown>;
}

/** A multiple-choice question the agent asks with a card (nexus_ask_user). */
export interface AgentQuestion {
  question: string;
  /** A 1-2 word label shown as a chip, e.g. "Alerts". */
  header: string;
  multi_select: boolean;
  options: { label: string; description: string }[];
}

export interface PendingQuestion {
  questions: AgentQuestion[];
}

/** Question text -> the chosen label(s), or the user's own words. */
export type QuestionAnswers = Record<string, string | string[]>;

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
  chat_settings?: ChatSettings;
}

export interface StoredMessage {
  role: MessageRole;
  content: string;
  events?: AgentEvent[];
  status?: string;
  summary?: string;
  usage?: ReplyUsage | null;
  citations?: Citation[] | null;
}

export interface AgentSession {
  id: number;
  session_id: string;
  title: string;
  messages: StoredMessage[];
  metadata?: {
    pending?: { state?: { queue?: { name: string; arguments: Record<string, unknown> }[] }; question?: PendingQuestion };
    settings?: ChatSettings;
    pinned?: boolean;
  };
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
  pending_question?: PendingQuestion | null;
  usage?: ReplyUsage | null;
  citations?: Citation[] | null;
}

export type AgentStreamEvent =
  | { type: 'tool_call'; tool: string; arguments: Record<string, unknown> }
  | { type: 'tool_result'; tool: string; ok: boolean; summary: string }
  | { type: 'approval_needed'; tool: string; arguments: Record<string, unknown> }
  | { type: 'question_needed'; questions: AgentQuestion[] }
  | { type: 'delta'; text: string }
  | { type: 'error'; error: string }
  | ({ type: 'done' } & AgentRunResponse);

export interface SendMessageRequest {
  content: string;
  attachments?: File[];
}
