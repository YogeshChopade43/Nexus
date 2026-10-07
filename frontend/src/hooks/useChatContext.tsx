import { createContext, useContext, useState, useCallback, useEffect, useRef, ReactNode } from 'react';
import { chatService } from '../services/chat';
import { useLLM } from './useLLM';
import { useLocalStorage } from './useUtils';
import { getErrorMessage } from '../lib/utils';
import type { ChatMessage, AgentRunResponse, AgentSession, StoredMessage } from '../types/chat';
import type { LLMProviderConfig } from '../types/llm';

interface ChatContextType {
  messages: ChatMessage[];
  sending: boolean;
  error: Error | null;
  sendMessage: (content: string, availableTools: string[]) => Promise<void>;
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

function buildAssistantMessage(response: AgentRunResponse): ChatMessage {
  return {
    id: newId(),
    role: 'assistant',
    content: response.response || response.message || '',
    timestamp: new Date().toISOString(),
    events: response.events,
    summary: response.summary,
    status: response.status,
  };
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
      setMessages(session.messages.map(m => fromStored(m, session.updated_at)));
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

  const sendMessage = useCallback(async (content: string, availableTools: string[] = []) => {
    if (!content.trim() || sendingRef.current || !hasLLM) return;
    sendingRef.current = true;
    setSending(true);
    setError(null);
    setMessages(prev => [...prev, { id: newId(), role: 'user', content, timestamp: new Date().toISOString() }]);

    try {
      let activeSession = sessionId;
      if (!activeSession) {
        activeSession = (await chatService.createSession(content.slice(0, 80))).session_id;
        setSessionId(activeSession);
      }
      const response = await chatService.runAgent({
        message: content,
        session_id: activeSession,
        available_tools: availableTools,
        llm_provider_id: providerId ?? undefined,
      });
      setMessages(prev => [...prev, buildAssistantMessage(response)]);
      void refreshSessions();
    } catch (err: unknown) {
      const message = getErrorMessage(err);
      setError(new Error(message));
      setMessages(prev => [...prev, {
        id: newId(),
        role: 'assistant',
        content: `Sorry, I encountered an error: ${message}`,
        timestamp: new Date().toISOString(),
        status: 'error',
      }]);
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }, [hasLLM, sessionId, setSessionId, providerId, refreshSessions]);

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
      messages, sending, error, sendMessage, clearMessages, hasLLM,
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
