import { useRef, useCallback, useEffect, useState } from 'react';
import { cn } from '../../lib/utils';
import { MessageList, MessageListRef } from './MessageList';
import { GettingStarted } from './GettingStarted';
import { Composer } from './Composer';
import { Button } from '../ui/Button';
import { Bot, Plus, AlertCircle, Workflow, History, SlidersHorizontal } from 'lucide-react';
import { ChatSettingsModal } from './ChatSettingsModal';
import { ConversationPanel } from './ConversationPanel';
import { useChatContext } from '../../hooks/useChatContext';
import { api } from '../../services/api';
import { Link, useNavigate } from 'react-router-dom';
import { chatService } from '../../services/chat';
import { getErrorMessage } from '../../lib/utils';
import type { ChatAttachment } from '../../types/chat';

interface ChatAreaProps {
  className?: string;
}

export function ChatArea({ className }: ChatAreaProps) {
  const [toolCount, setToolCount] = useState<number | null>(null);
  const [converting, setConverting] = useState(false);
  const [convertError, setConvertError] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const navigate = useNavigate();
  const {
    messages, sending, error, sendMessage, answerApproval, answerQuestions, stop, retry, clearMessages, hasLLM,
    providers, providerId, setProviderId, sessionId, sessions, openSession, deleteSession, refreshSessions,
    settings, saveSettings,
  } = useChatContext();
  const customized = settings.servers !== null || settings.instructions.trim() !== '' || settings.temperature !== null || settings.library_id !== null;
  const messageListRef = useRef<MessageListRef>(null);

  useEffect(() => {
    api.get<{ tools: string[] }>('/api/tools/available')
      .then(r => setToolCount(r.tools.filter(name => !name.startsWith('nexus__')).length)) // built-ins aren't from servers
      .catch(() => setToolCount(null));
  }, []);

  const handleSend = useCallback(async (content: string, attachments: ChatAttachment[], uploads: File[]) => {
    // No explicit tool list: the backend offers the tools of connected MCP servers (see chat settings).
    await sendMessage(content, attachments, uploads);
    messageListRef.current?.scrollToBottom();
  }, [sendMessage]);

  const lastStatus = messages[messages.length - 1]?.status;
  const awaiting = lastStatus === 'needs_approval' || lastStatus === 'needs_input';
  const usedTools = messages.some(m => m.events?.some(e => e.type === 'tool_executed'));
  const turnIntoWorkflow = async () => {
    if (!sessionId) return;
    setConverting(true);
    setConvertError(null);
    try {
      const workflow = await chatService.toWorkflow(sessionId);
      navigate(`/workflows?open=${workflow.id}`);
    } catch (err) {
      setConvertError(getErrorMessage(err));
    } finally {
      setConverting(false);
    }
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text).catch(() => {});
  };

  return (
    <div className={cn('relative flex flex-col h-full bg-nexus-bg-secondary border-nexus-border rounded-xl overflow-hidden', className)}>
      <div className="p-4 border-b-nexus-border border-b flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-nexus-accent-dim flex items-center justify-center">
            <Bot className="w-5 h-5 text-nexus-accent" />
          </div>
          <div>
            <h2 className="font-semibold text-nexus-text">Nexus Agent</h2>
            <p className="text-xs text-nexus-text-secondary">
              {toolCount === null ? 'MCP tools unavailable' : (
                <>{toolCount} tool(s) from <Link to="/servers" className="underline">your apps</Link></>
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
          <Button variant="ghost" size="sm" onClick={() => setHistoryOpen(o => !o)} aria-label="Conversations" title="Past conversations" aria-expanded={historyOpen}>
            <History className="w-4 h-4" />
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setSettingsOpen(true)} aria-label="Chat settings" title="Settings for this chat"
            className={cn(customized && 'text-nexus-accent')}>
            <SlidersHorizontal className="w-4 h-4" />
          </Button>
          {sessionId && usedTools && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void turnIntoWorkflow()}
              disabled={converting || sending}
              className="gap-1.5"
              title="Save the tool calls from this conversation as a workflow you can re-run"
            >
              <Workflow className="w-4 h-4" />
              {converting ? 'Creating…' : 'Turn into workflow'}
            </Button>
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

      {historyOpen && (
        <ConversationPanel
          sessions={sessions}
          currentId={sessionId}
          onSearch={(q) => void refreshSessions(q)}
          onOpen={(id) => { void openSession(id); setHistoryOpen(false); }}
          onDelete={deleteSession}
          onClose={() => setHistoryOpen(false)}
        />
      )}
      <ChatSettingsModal open={settingsOpen} settings={settings} onSave={saveSettings} onClose={() => setSettingsOpen(false)} />

      {convertError && (
        <div className="p-3 border-b-nexus-danger/30 border-b bg-red-500/5 text-sm text-nexus-danger">{convertError}</div>
      )}
      {error && (
        <div className="p-3 border-b-nexus-danger/30 border-b bg-red-500/5">
          <div className="flex items-center gap-2 text-nexus-danger">
            <AlertCircle className="w-5 h-5 flex-shrink-0" />
            <span>{error.message || error.toString() || 'Something went wrong'}</span>
          </div>
        </div>
      )}

      {messages.length === 0 && <GettingStarted hasLLM={hasLLM} />}
      <MessageList
        ref={messageListRef}
        messages={messages}
        onCopy={handleCopy}
        onApprove={sending ? undefined : (approved) => void answerApproval(approved)}
        onAnswer={sending ? undefined : (answers) => void answerQuestions(answers)}
        onRetry={sending || !sessionId ? undefined : () => void retry()}
        onEdit={sending || !sessionId ? undefined : (text) => void retry(text)}
        onPickPrompt={hasLLM && !sending ? (text) => void handleSend(text, [], []) : undefined}
        autoScroll={true}
      />
      <Composer
        onSend={handleSend}
        disabled={sending || !hasLLM || awaiting}
        running={sending}
        onStop={stop}
        placeholder={!hasLLM ? 'Configure an LLM provider in Settings to start chatting...' : awaiting ? (lastStatus === 'needs_input' ? 'Answer the questions above to continue...' : 'Approve or deny the action above to continue...') : messages.length === 0 ? 'Start a conversation...' : 'Message Agent...'}
      />
    </div>
  );
}
