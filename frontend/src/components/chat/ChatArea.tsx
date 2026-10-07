import { useRef, useCallback, useEffect, useState } from 'react';
import { cn } from '../../lib/utils';
import { MessageList, MessageListRef } from './MessageList';
import { Composer } from './Composer';
import { Button } from '../ui/Button';
import { Bot, Plus, Settings, Sparkles, AlertCircle, Trash2 } from 'lucide-react';
import { useChatContext } from '../../hooks/useChatContext';
import { api } from '../../services/api';
import { Link } from 'react-router-dom';

interface ChatAreaProps {
  className?: string;
}

export function ChatArea({ className }: ChatAreaProps) {
  const [toolCount, setToolCount] = useState<number | null>(null);
  const {
    messages, sending, error, sendMessage, clearMessages, hasLLM,
    providers, providerId, setProviderId, sessionId, sessions, openSession, deleteSession,
  } = useChatContext();
  const messageListRef = useRef<MessageListRef>(null);

  useEffect(() => {
    api.get<{ tools: string[] }>('/api/tools/available')
      .then(r => setToolCount(r.tools.length))
      .catch(() => setToolCount(null));
  }, []);

  const handleSend = useCallback(async (content: string) => {
    // No explicit tool list: the backend offers every tool from connected MCP servers.
    await sendMessage(content, []);
    messageListRef.current?.scrollToBottom();
  }, [sendMessage]);

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text).catch(() => {});
  };

  const isAgentRunning = sending;

  return (
    <div className={cn('flex flex-col h-full bg-nexus-bg-secondary border-nexus-border rounded-xl overflow-hidden', className)}>
      <div className="p-4 border-b-nexus-border border-b flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-nexus-accent-dim flex items-center justify-center">
            <Bot className="w-5 h-5 text-nexus-accent" />
          </div>
          <div>
            <h2 className="font-semibold text-nexus-text">Nexus Agent</h2>
            <p className="text-xs text-nexus-text-secondary">
              {toolCount === null ? 'MCP tools unavailable' : (
                <>{toolCount} tool(s) from <Link to="/servers" className="underline">MCP servers</Link></>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap justify-end">
          {providers.length > 0 && (
            <select
              value={providerId ?? ''}
              onChange={(e) => setProviderId(e.target.value ? Number(e.target.value) : null)}
              aria-label="Language model"
              className="max-w-[12rem] px-2 py-1.5 rounded-lg bg-nexus-bg-tertiary border border-nexus-border text-xs text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent"
            >
              {providers.map(p => (
                <option key={p.id} value={p.id}>{p.provider_name} · {p.model}</option>
              ))}
            </select>
          )}
          {sessions.length > 0 && (
            <select
              value={sessionId ?? ''}
              onChange={(e) => { if (e.target.value) void openSession(e.target.value); else clearMessages(); }}
              aria-label="Conversation"
              className="max-w-[12rem] px-2 py-1.5 rounded-lg bg-nexus-bg-tertiary border border-nexus-border text-xs text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent"
            >
              <option value="">New conversation</option>
              {sessions.map(s => (
                <option key={s.session_id} value={s.session_id}>{s.title || 'Untitled conversation'}</option>
              ))}
            </select>
          )}
          {sessionId && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => { if (window.confirm('Delete this conversation?')) void deleteSession(sessionId); }}
              aria-label="Delete conversation"
            >
              <Trash2 className="w-4 h-4" />
            </Button>
          )}
          {sending && (
            <span className="text-xs text-nexus-text-secondary flex items-center gap-1.5">
              <Sparkles className="w-3 h-3 text-nexus-accent animate-pulse" />
              Agent is thinking...
            </span>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={clearMessages}
            aria-label="Start a new conversation"
            className="gap-1.5"
          >
            <Plus className="w-4 h-4" />
            New chat
          </Button>
        </div>
      </div>

      {error && (
        <div className="p-3 border-b-nexus-danger/30 border-b bg-red-500/5">
          <div className="flex items-center gap-2 text-nexus-danger">
            <AlertCircle className="w-5 h-5 flex-shrink-0" />
            <span>{error.message || error.toString() || 'Something went wrong'}</span>
          </div>
        </div>
      )}

      <MessageList
        ref={messageListRef}
        messages={messages}
        onCopy={handleCopy}
        autoScroll={true}
      />
      {sending && (
        <div className="px-4 pb-4">
          <div className="flex gap-3 animate-slide-up">
            <div className="w-8 h-8 rounded-full bg-nexus-accent-dim flex items-center justify-center flex-shrink-0 mt-1">
              <Bot className="w-5 h-5 text-nexus-accent" />
            </div>
            <div className="flex-1 max-w-[85%]">
              <div className="inline-block px-4 py-2.5 rounded-2xl bg-nexus-bg-secondary border-nexus-border rounded-tl-none">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-nexus-text-secondary">Nexus is thinking</span>
                  <span className="thinking-dots text-nexus-text-secondary/50">
                    <span>.</span><span>.</span><span>.</span>
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
      {!hasLLM && messages.length === 0 && (
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
