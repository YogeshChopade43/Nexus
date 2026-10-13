import { createContext, useContext, useState, useCallback, useEffect, useRef, ReactNode } from 'react';
import { chatService } from '../services/chat';
import { ragService, settled, uploadFiles } from '../services/rag';
import { useLLM } from './useLLM';
import { useLocalStorage } from './useUtils';
import { getErrorMessage } from '../lib/utils';
import {
  DEFAULT_CHAT_SETTINGS,
  type AgentRunResponse, type AgentSession, type AgentStreamEvent, type ChatAttachment, type ChatMessage,
  type ChatSettings, type FileRef, type StoredMessage, type ToolActivity,
  type QuestionAnswers,
} from '../types/chat';
import type { LLMProviderConfig } from '../types/llm';

interface ChatContextType {
  messages: ChatMessage[];
  sending: boolean;
  error: Error | null;
  /** Inline text attachments go into the message; ``uploads`` are added to the knowledge base first. */
  sendMessage: (content: string, attachments?: ChatAttachment[], uploads?: File[]) => Promise<void>;
  answerApproval: (approved: boolean) => Promise<void>;
  answerQuestions: (answers: QuestionAnswers) => Promise<void>;
  /** Stop the reply being written; what was said so far is kept. */
  stop: () => void;
  /** Ask again: the last question, or ``newText`` in its place (edit). */
  retry: (newText?: string) => Promise<void>;
  clearMessages: () => void;
  hasLLM: boolean;
  providers: LLMProviderConfig[];
  providerId: number | null;
  setProviderId: (id: number | null) => void;
  sessionId: string | null;
  sessions: AgentSession[];
  openSession: (sessionId: string) => Promise<void>;
  deleteSession: (sessionId: string) => Promise<void>;
  refreshSessions: (query?: string) => Promise<void>;
  settings: ChatSettings;
  saveSettings: (settings: ChatSettings) => Promise<void>;
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
    pendingQuestion: response.pending_question ?? undefined,
    usage: response.usage ?? undefined,
    citations: response.citations ?? undefined,
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

const isAbort = (err: unknown) => err instanceof DOMException && err.name === 'AbortError';
/** How long to wait for attached files to be processed before giving up. */
const UPLOAD_WAIT_MS = 180_000;

export function ChatProvider({ children }: { children: ReactNode }) {
  const { configs } = useLLM();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [sessionId, setSessionId] = useLocalStorage<string | null>('nexus-chat-session', null);
  const [storedProviderId, setProviderId] = useLocalStorage<number | null>('nexus-chat-provider', null);
  const [settings, setSettings] = useState<ChatSettings>(DEFAULT_CHAT_SETTINGS);
  const sendingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const providers = configs.filter(c => c.enabled);
  const hasLLM = providers.length > 0;
  // Fall back to the first enabled provider if the remembered one was removed or disabled.
  const providerId = providers.some(p => p.id === storedProviderId) ? storedProviderId : providers[0]?.id ?? null;

  const refreshSessions = useCallback(async (query = '') => {
    try {
      setSessions(await chatService.listSessions(query));
    } catch {
      // The conversation list is a convenience; chatting still works without it.
    }
  }, []);

  const openSession = useCallback(async (id: string) => {
    try {
      const session = await chatService.getSession(id);
      const restored = session.messages.map(m => fromStored(m, session.updated_at));
      // A paused run isn't in the message list yet; show its question cards or approval card again.
      const question = session.metadata?.pending?.question;
      const waiting = session.metadata?.pending?.state?.queue?.[0];
      if (question) {
        restored.push({
          id: newId(), role: 'assistant', timestamp: session.updated_at, status: 'needs_input',
          content: 'Nexus has a question for you.', pendingQuestion: question,
        });
      } else if (waiting) {
        restored.push({
          id: newId(), role: 'assistant', timestamp: session.updated_at, status: 'needs_approval',
          content: `Nexus wants to run ${waiting.name}. Approve or deny it to continue.`,
          pendingAction: { tool: waiting.name, arguments: waiting.arguments },
        });
      }
      setMessages(restored);
      setSettings({ ...DEFAULT_CHAT_SETTINGS, ...session.metadata?.settings });
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

  /**
   * Stream one reply into the message ``assistantId``: progress events update it live, ``done``
   * fills in the final answer. Stop (abort) keeps what was written; the server saves it too.
   */
  const streamInto = useCallback(async (assistantId: string, start: (onEvent: (e: AgentStreamEvent) => void, signal: AbortSignal) => Promise<void>) => {
    sendingRef.current = true;
    setSending(true);
    setError(null);
    const controller = new AbortController();
    abortRef.current = controller;
    const update = (change: (m: ChatMessage) => ChatMessage) =>
      setMessages(prev => prev.map(m => (m.id === assistantId ? change(m) : m)));
    try {
      let final = null as AgentRunResponse | null; // cast: assigned inside the callback, TS would narrow it to null
      let streamError = '';
      await start((event) => {
        if (event.type === 'done') final = event;
        else if (event.type === 'error') streamError = event.error;
        else update(m => applyStreamEvent(m, event));
      }, controller.signal);
      if (streamError) throw new Error(streamError);
      if (!final) throw new Error('The connection closed before the agent finished');
      const response: AgentRunResponse = final;
      if (response.session_id) setSessionId(response.session_id);
      update(m => ({ ...m, ...fromResponse(response) }));
    } catch (err: unknown) {
      if (isAbort(err)) {
        update(m => ({ ...m, status: 'cancelled', activity: undefined, content: m.content ? `${m.content}\n\n_(stopped)_` : '_(stopped before answering)_' }));
      } else {
        const message = getErrorMessage(err);
        setError(new Error(message));
        update(m => ({ ...m, content: `Sorry, I encountered an error: ${message}`, status: 'error', activity: undefined, pendingAction: undefined }));
      }
    } finally {
      abortRef.current = null;
      sendingRef.current = false;
      setSending(false);
      void refreshSessions();
    }
  }, [setSessionId, refreshSessions]);

  const ask = useCallback(async (content: string, shown: string, attachments: ChatAttachment[], targetSession: string | null,
    files: FileRef[] = []) => {
    const assistantId = newId();
    const now = new Date().toISOString();
    setMessages(prev => [
      ...prev,
      { id: newId(), role: 'user', content: shown, timestamp: now, files },
      { id: assistantId, role: 'assistant', content: '', timestamp: now, status: 'running', activity: [] },
    ]);
    // The server creates the session if there is none and reports it in the final event.
    await streamInto(assistantId, (onEvent, signal) => chatService.streamAgent({
      message: content,
      session_id: targetSession ?? undefined,
      llm_provider_id: providerId ?? undefined,
      attachments,
      files,
      chat_settings: settings,
    }, onEvent, signal));
  }, [streamInto, providerId, settings]);

  const sendMessage = useCallback(async (content: string, attachments: ChatAttachment[] = [], uploads: File[] = []) => {
    if ((!content.trim() && attachments.length === 0 && uploads.length === 0) || sendingRef.current || !hasLLM) return;
    let text = content;
    let target = sessionId;
    if (uploads.length) {
      // PDFs and big files go into this chat's own collection; the agent searches them instead of
      // reading them whole. Wait until they're processed so the agent can use them right away.
      try {
        sendingRef.current = true;
        setSending(true);
        if (!target) {
          target = (await chatService.createSession(content.slice(0, 80) || uploads[0].name)).session_id;
          setSessionId(target);
        }
        let docs = await ragService.uploadToChat(target, uploads);
        const deadline = Date.now() + UPLOAD_WAIT_MS;
        while (docs.some(d => !settled(d)) && Date.now() < deadline) {
          await new Promise(resolve => setTimeout(resolve, 700));
          docs = await Promise.all(docs.map(d => ragService.document(d.id)));
        }
        const failed = docs.filter(d => d.status === 'failed');
        if (failed.length) throw new Error(failed.map(d => `${d.name}: ${d.error}`).join('; '));
        text = `${content}\n\n(I attached ${docs.map(d => `"${d.name}"`).join(', ')}. They're searchable in this chat.)`.trim();
      } catch (err) {
        setError(new Error(`Could not add the file: ${getErrorMessage(err)}`));
        return;
      } finally {
        sendingRef.current = false;
        setSending(false);
      }
    }
    // Keep a copy of every attached file so the chat can preview it; the message still goes if that fails.
    const picked = [...attachments.map(a => new File([a.content], a.name, { type: 'text/plain' })), ...uploads];
    const files = picked.length ? await uploadFiles<FileRef[]>('/api/files', picked).catch(() => []) : [];
    await ask(text, content, attachments, target, files);
  }, [hasLLM, ask, sessionId, setSessionId]);

  const answerApproval = useCallback(async (approved: boolean) => {
    const waiting = [...messages].reverse().find(m => m.status === 'needs_approval');
    if (!waiting || !sessionId || sendingRef.current) return;
    setMessages(prev => prev.map(m => (m.id === waiting.id
      ? { ...m, status: 'running', content: '', pendingAction: undefined, activity: [] }
      : m)));
    await streamInto(waiting.id, (onEvent, signal) => chatService.streamApproval(sessionId, approved, onEvent, signal));
  }, [messages, sessionId, streamInto]);

  const answerQuestions = useCallback(async (answers: QuestionAnswers) => {
    const waiting = [...messages].reverse().find(m => m.status === 'needs_input');
    if (!waiting || !sessionId || sendingRef.current) return;
    setMessages(prev => prev.map(m => (m.id === waiting.id
      ? { ...m, status: 'running', content: '', pendingQuestion: undefined, activity: [],
          events: [...(m.events ?? []), { type: 'user_answered', answers }] }
      : m)));
    await streamInto(waiting.id, (onEvent, signal) => chatService.streamAnswers(sessionId, answers, onEvent, signal));
  }, [messages, sessionId, streamInto]);

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const retry = useCallback(async (newText?: string) => {
    if (!sessionId || sendingRef.current) return;
    let previous: string;
    try {
      previous = (await chatService.rewind(sessionId)).message;
    } catch (err) {
      setError(new Error(getErrorMessage(err)));
      return;
    }
    const lastUser = messages.map(m => m.role).lastIndexOf('user');
    setMessages(prev => (lastUser >= 0 ? prev.slice(0, lastUser) : prev));
    const text = newText?.trim() || previous;
    await ask(text, text, [], sessionId);
  }, [sessionId, messages, ask]);

  const saveSettings = useCallback(async (next: ChatSettings) => {
    setSettings(next);
    if (sessionId) await chatService.saveSettings(sessionId, next);
  }, [sessionId]);

  const clearMessages = useCallback(() => {
    // Start a new conversation; the old one stays available in the conversation list.
    setMessages([]);
    setError(null);
    setSessionId(null);
    setSettings(DEFAULT_CHAT_SETTINGS);
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
      messages, sending, error, sendMessage, answerApproval, answerQuestions, stop, retry, clearMessages, hasLLM,
      providers, providerId, setProviderId,
      sessionId, sessions, openSession, deleteSession, refreshSessions, settings, saveSettings,
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
