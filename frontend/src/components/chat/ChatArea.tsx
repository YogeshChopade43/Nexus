import { ContextMeter } from './ContextMeter';
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
    <div className={cn('relative -mx-4 -my-4 flex h-[calc(100dvh-3.5rem)] flex-col lg:-mx-8 lg:-my-6', className)}>
      <div className="flex items-center justify-between gap-3 border-b border-nexus-border px-4 py-2 lg:px-6">
        <p className="hidden min-w-0 items-center gap-2 text-xs text-nexus-text-muted sm:flex">
          <Bot className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="truncate">
            {toolCount === null ? 'App tools unavailable' : (
              <>{toolCount} tool(s) from <Link to="/servers">your apps</Link></>
            )}
          </span>
        </p>
        <div className="ml-auto flex items-center gap-1">
          {providers.length > 0 && (
            <select
              value={providerId ?? ''}
              onChange={(e) => setProviderId(e.target.value ? Number(e.target.value) : null)}
              aria-label="Language model"
              className="mr-1 h-8 max-w-[9rem] sm:max-w-[13rem] rounded-md border border-nexus-border bg-nexus-bg-secondary pl-2.5 text-xs text-nexus-text shadow-surface"
            >
              {providers.map(p => (
                <option key={p.id} value={p.id}>{p.provider_name} · {p.model}</option>
              ))}
            </select>
          )}
          {hasLLM && <ContextMeter messages={messages} providerId={providerId} />}
          <Button variant="ghost" size="sm" className="w-8 px-0" onClick={() => setHistoryOpen(o => !o)} aria-label="Conversations" title="Past conversations" aria-expanded={historyOpen}>
            <History className="w-4 h-4" />
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setSettingsOpen(true)} aria-label="Chat settings" title="Settings for this chat"
            className={cn('w-8 px-0', customized && 'text-nexus-accent-text')}>
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
              <Workflow className="w-3.5 h-3.5" />
              {converting ? 'Creating…' : 'Turn into workflow'}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={clearMessages}
            aria-label="Start a new conversation"
          >
            <Plus className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">New chat</span>
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
        <div className="border-b border-nexus-danger/30 bg-nexus-danger/5 px-6 py-2.5 text-[13px] text-nexus-danger">{convertError}</div>
      )}
      {error && (
        <div className="border-b border-nexus-danger/30 bg-nexus-danger/5 px-6 py-2.5 text-[13px]">
          <div className="flex items-center gap-2 text-nexus-danger">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span>{error.message || error.toString() || 'Something went wrong'}</span>
          </div>
        </div>
      )}

      <MessageList
        intro={<GettingStarted hasLLM={hasLLM} />}
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
