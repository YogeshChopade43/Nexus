import { useState, useCallback } from 'react';
import { chatService } from '../services/chat';
import { useLLM } from './useLLM';
import type { ChatMessage, AgentRunResponse } from '../types/chat';

interface UseChatReturn {
  messages: ChatMessage[];
  sending: boolean;
  error: Error | null;
  sendMessage: (content: string) => Promise<void>;
  clearMessages: () => void;
  hasLLM: boolean;
}

function buildAssistantMessage(response: AgentRunResponse): ChatMessage {
  const content = response.message ?? response.response ?? '';
  return {
    id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
    role: 'assistant',
    content,
    timestamp: new Date().toISOString(),
  };
}

function buildUserMessage(content: string): ChatMessage {
  return {
    id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
    role: 'user',
    content,
    timestamp: new Date().toISOString(),
  };
}

export function useChat(availableTools: string[] = []): UseChatReturn {
  const { configs } = useLLM();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const hasLLM = configs.some(c => c.enabled);

  const sendMessage = useCallback(async (content: string): Promise<void> => {
    if (!content.trim() || sending) return;
    if (!hasLLM) return;

    const userMessage = buildUserMessage(content);
    setMessages(prev => [...prev, userMessage]);
    setSending(true);
    setError(null);

    try {
      const enabledConfig = configs.find(c => c.enabled);
      const response = await chatService.runAgent({
        message: content,
        context: {
          previousMessages: messages.slice(-6).map(m => ({ role: m.role, content: m.content })),
        },
        available_tools: availableTools,
        llm_provider_id: enabledConfig?.id,
      });

      const assistantMessage = buildAssistantMessage(response);
      setMessages(prev => [...prev, assistantMessage]);
    } catch (err) {
      setError(err as Error);
      setMessages(prev => [...prev, {
        id: `msg-${Date.now()}-error`,
        role: 'assistant',
        content: `Sorry, I encountered an error: ${(err as Error).message || 'Unknown error'}`,
        timestamp: new Date().toISOString(),
      }]);
    } finally {
      setSending(false);
    }
  }, [messages, sending, availableTools, hasLLM, configs]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
  }, []);

  return { messages, sending, error, sendMessage, clearMessages, hasLLM };
}
