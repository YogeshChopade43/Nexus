import { createContext, useContext, useState, useCallback, useEffect, useRef, ReactNode } from 'react';
import { chatService } from '../services/chat';
import { useLLM } from './useLLM';
import { useLocalStorage } from './useUtils';
import { getErrorMessage } from '../lib/utils';
import type { ChatAttachment, ChatMessage, AgentRunResponse, AgentSession, AgentStreamEvent, StoredMessage, ToolActivity } from '../types/chat';
import type { LLMProviderConfig } from '../types/llm';

interface ChatContextType {
  messages: ChatMessage[];
  sending: boolean;
  error: Error | null;
  sendMessage: (content: string, attachments?: ChatAttachment[]) => Promise<void>;
  answerApproval: (approved: boolean) => Promise<void>;
  clearMessages: () => void;
  hasLLM: boolean;
  providers: LLMProviderConfig[];
  providerId: number | null;
  setProviderId: (id: number | null) => void;
  sessionId: string | null;
  sessions: AgentSession[];
  openSession: (sessionId: string) => Promise<void>;
  deleteSession: (sessionId: string) => Promise<void>;
  refreshSessions: () => Promise<void>;
}

const ChatContext = createContext<ChatContextType | null>(null);

function newId(): string {
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function fromResponse(response: AgentRunResponse): Partial<ChatMessage> {
  return {
    content: response.response || response.message || '',
    events: response.events,
    summary: response.summary,
    status: response.status,
    activity: undefined,
    pendingAction: response.pending_action ?? undefined,
  };
}

function applyStreamEvent(message: ChatMessage, event: AgentStreamEvent): ChatMessage {
  const activity = message.activity ?? [];
  switch (event.type) {
    case 'tool_call':
      return { ...message, activity: [...activity, { tool: event.tool, state: 'running' }] };
    case 'tool_result': {
      const done: ToolActivity = { tool: event.tool, state: event.ok ? 'ok' : 'failed', summary: event.summary };
      const index = activity.findIndex(a => a.tool === event.tool && a.state === 'running');
      return { ...message, activity: index < 0 ? [...activity, done] : activity.map((a, i) => (i === index ? done : a)) };
    }
    case 'delta':
      return { ...message, content: message.content + event.text };
    default:
      return message;
  }
}

function fromStored(message: StoredMessage, timestamp: string): ChatMessage {
  return { id: newId(), timestamp, ...message };
}

export function ChatProvider({ children }: { children: ReactNode }) {
  const { configs } = useLLM();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [sessionId, setSessionId] = useLocalStorage<string | null>('nexus-chat-session', null);
  const [storedProviderId, setProviderId] = useLocalStorage<number | null>('nexus-chat-provider', null);
  const sendingRef = useRef(false);

  const providers = configs.filter(c => c.enabled);
  const hasLLM = providers.length > 0;
  // Fall back to the first enabled provider if the remembered one was removed or disabled.
  const providerId = providers.some(p => p.id === storedProviderId) ? storedProviderId : providers[0]?.id ?? null;

  const refreshSessions = useCallback(async () => {
    try {
      setSessions(await chatService.listSessions());
    } catch {
      // The conversation list is a convenience; chatting still works without it.
    }
  }, []);

  const openSession = useCallback(async (id: string) => {
    try {
      const session = await chatService.getSession(id);
      const restored = session.messages.map(m => fromStored(m, session.updated_at));
      // A run paused for approval isn't in the message list yet; show its approval card again.
      const waiting = session.metadata?.pending?.state?.queue?.[0];
      if (waiting) {
        restored.push({
          id: newId(), role: 'assistant', timestamp: session.updated_at, status: 'needs_approval',
          content: `Nexus wants to run ${waiting.name}. Approve or deny it to continue.`,
          pendingAction: { tool: waiting.name, arguments: waiting.arguments },
        });
      }
      setMessages(restored);
      setSessionId(id);
      setError(null);
    } catch {
      setSessionId(null);
      setMessages([]);
    }
  }, [setSessionId]);

  // Restore the last conversation once on load.
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    if (sessionId) void openSession(sessionId);
    void refreshSessions();
  }, [sessionId, openSession, refreshSessions]);

  const fail = useCallback((assistantId: string, err: unknown) => {
    const message = getErrorMessage(err);
    setError(new Error(message));
    setMessages(prev => prev.map(m => (m.id === assistantId
      ? { ...m, content: `Sorry, I encountered an error: ${message}`, status: 'error', activity: undefined, pendingAction: undefined }
      : m)));
  }, []);

  const sendMessage = useCallback(async (content: string, attachments: ChatAttachment[] = []) => {
    if ((!content.trim() && attachments.length === 0) || sendingRef.current || !hasLLM) return;
    sendingRef.current = true;
    setSending(true);
    setError(null);
    const shown = attachments.length ? `${content}

📎 ${attachments.map(a => a.name).join(', ')}`.trim() : content;
    const assistantId = newId();
    const now = new Date().toISOString();
    setMessages(prev => [
      ...prev,
      { id: newId(), role: 'user', content: shown, timestamp: now },
      { id: assistantId, role: 'assistant', content: '', timestamp: now, status: 'running', activity: [] },
    ]);
    const update = (change: (m: ChatMessage) => ChatMessage) =>
      setMessages(prev => prev.map(m => (m.id === assistantId ? change(m) : m)));

    try {
      let final = null as AgentRunResponse | null; // cast: assigned inside the callback, TS would narrow it to null
      let streamError = '';
      // The server creates the session if there is none and reports it in the final event.
      await chatService.streamAgent({
        message: content,
        session_id: sessionId ?? undefined,
        llm_provider_id: providerId ?? undefined,
        attachments,
      }, (event) => {
        if (event.type === 'done') final = event;
        else if (event.type === 'error') streamError = event.error;
        else update(m => applyStreamEvent(m, event));
      });
      if (streamError) throw new Error(streamError);
      if (!final) throw new Error('The connection closed before the agent finished');
      const response: AgentRunResponse = final;
      if (response.session_id) setSessionId(response.session_id);
      update(m => ({ ...m, ...fromResponse(response) }));
      void refreshSessions();
    } catch (err: unknown) {
      fail(assistantId, err);
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }, [hasLLM, sessionId, setSessionId, providerId, refreshSessions, fail]);

  const answerApproval = useCallback(async (approved: boolean) => {
    const waiting = [...messages].reverse().find(m => m.status === 'needs_approval');
    if (!waiting || !sessionId || sendingRef.current) return;
    sendingRef.current = true;
    setSending(true);
    setError(null);
    setMessages(prev => prev.map(m => (m.id === waiting.id
      ? { ...m, status: 'running', content: '', pendingAction: undefined, activity: approved ? [{ tool: waiting.pendingAction?.tool ?? 'tool', state: 'running' }] : [] }
      : m)));
    try {
      const response = await chatService.answerApproval(sessionId, approved);
      setMessages(prev => prev.map(m => (m.id === waiting.id ? { ...m, ...fromResponse(response) } : m)));
      void refreshSessions();
    } catch (err: unknown) {
      fail(waiting.id, err);
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }, [messages, sessionId, refreshSessions, fail]);

  const clearMessages = useCallback(() => {
    // Start a new conversation; the old one stays available in the conversation list.
    setMessages([]);
    setError(null);
    setSessionId(null);
  }, [setSessionId]);

  const deleteSession = useCallback(async (id: string) => {
    try {
      await chatService.deleteSession(id);
    } catch (err) {
      setError(new Error(getErrorMessage(err)));
      return;
    }
    if (id === sessionId) clearMessages();
    await refreshSessions();
  }, [sessionId, clearMessages, refreshSessions]);

  return (
    <ChatContext.Provider value={{
      messages, sending, error, sendMessage, answerApproval, clearMessages, hasLLM,
      providers, providerId, setProviderId,
      sessionId, sessions, openSession, deleteSession, refreshSessions,
    }}>
      {children}
    </ChatContext.Provider>
  );
}

export function useChatContext() {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error('useChatContext must be used within a ChatProvider');
  }
  return context;
}
