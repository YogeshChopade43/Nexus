import { useRef, useCallback } from 'react';
import { cn } from '../../lib/utils';
import { MessageList, MessageListRef } from './MessageList';
import { Composer } from './Composer';
import { Button } from '../ui/Button';
import { Bot, RefreshCw, Settings, Sparkles } from 'lucide-react';
import { useChat } from '../../hooks/useChat';
import { useApps } from '../../hooks/useApps';
import { Link } from 'react-router-dom';
import type { ChatMessage } from '../../types/chat';

interface ChatAreaProps {
  className?: string;
}

export function ChatArea({ className }: ChatAreaProps) {
  const apps = useApps();
  const { messages, sending, error, sendMessage, clearMessages, hasLLM } = useChat(apps.availableTools);
  const messageListRef = useRef<MessageListRef>(null);

  const handleSend = useCallback(async (content: string) => {
    await sendMessage(content);
    messageListRef.current?.scrollToBottom();
  }, [sendMessage]);

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text).catch(() => {});
  };

  const assistantMessages = messages.filter((m: ChatMessage) => m.role === 'assistant');
  const lastAssistantMessage = assistantMessages[assistantMessages.length - 1];
  const isAgentRunning = sending && lastAssistantMessage && !lastAssistantMessage.content;

  return (
    <div className={cn('flex flex-col h-full bg-nexus-bg-secondary border-nexus-border rounded-xl overflow-hidden', className)}>
      <div className="p-4 border-b-nexus-border border-b flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-nexus-accent-dim flex items-center justify-center">
            <Bot className="w-5 h-5 text-nexus-accent" />
          </div>
          <div>
            <h2 className="font-semibold text-nexus-text">Nexus Agent</h2>
            <p className="text-xs text-nexus-text-secondary">Connected to /api/agent/run</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {sending && (
            <span className="text-xs text-nexus-text-secondary">Agent is thinking...</span>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={clearMessages}
            aria-label="Clear conversation"
            className="gap-1.5"
          >
            <RefreshCw className="w-4 h-4" />
            Clear
          </Button>
        </div>
      </div>

      {error && (
        <div className="p-3 border-b-nexus-danger/30 border-b bg-red-500/5">
          <div className="flex items-center gap-2 text-nexus-danger">
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span>{error.message || 'Something went wrong'}</span>
          </div>
        </div>
      )}

      <MessageList
        ref={messageListRef}
        messages={messages}
        onCopy={handleCopy}
        autoScroll={true}
      />
      {!hasLLM && (
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="max-w-sm text-center space-y-4">
            <div className="w-16 h-16 rounded-2xl bg-nexus-accent-dim flex items-center justify-center mx-auto">
              <Sparkles className="w-8 h-8 text-nexus-accent" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-nexus-text">No LLM Provider Configured</h3>
              <p className="text-sm text-nexus-text-secondary mt-1">
                Configure an AI provider in Settings to start chatting with Nexus.
              </p>
            </div>
            <Link to="/settings" className="inline-flex items-center gap-2 px-4 py-2 bg-nexus-accent text-nexus-bg rounded-lg text-sm font-medium hover:opacity-90 transition-opacity">
              <Settings className="w-4 h-4" />
              Go to Settings
            </Link>
          </div>
        </div>
      )}
      <Composer
        onSend={handleSend}
        disabled={sending || isAgentRunning || !hasLLM}
        placeholder={!hasLLM ? 'Configure an LLM provider in Settings to start chatting...' : messages.length === 0 ? 'Start a conversation...' : 'Message Agent...'}
      />
    </div>
  );
}
