import { MadeFiles, ToolSources } from './ToolSources';
import { FileChip } from './FilePreview';
import { MentionText, useMentionLabels } from './MentionText';
import { Logo } from '../layout/Sidebar';
import { cn, formatRelativeTime } from '../../lib/utils';
import { useState } from 'react';
import { Copy, Bot, AlertCircle, CheckCircle2, Info, Ban, Loader2, ShieldQuestion, RotateCcw, Pencil, Gauge } from 'lucide-react';
import { Markdown } from './Markdown';
import { Sources } from './Sources';
import { ToolName } from './ToolName';
import { AnsweredQuestions, QuestionCard } from './QuestionCard';
import { ApprovalDetails } from './ApprovalDetails';
import { Button } from '../ui/Button';
import { Tooltip } from '../ui/Tooltip';
import type { QuestionAnswers, ChatMessage, AgentEvent } from '../../types/chat';
import type { ReactNode } from 'react';

const EVENT_ICONS: Record<string, React.ElementType> = {
  tool_executed: CheckCircle2,
  tool_error: AlertCircle,
  app_unavailable: Info,
  intent_no_match: Bot,
  llm_error: AlertCircle,
  tool_declined: Ban,
  step_limit: Gauge,
};

const EVENT_COLORS: Record<string, string> = {
  tool_executed: 'text-green-400',
  tool_error: 'text-red-400',
  app_unavailable: 'text-amber-400',
  intent_no_match: 'text-nexus-text-muted',
  llm_error: 'text-red-400',
  tool_declined: 'text-amber-400',
  step_limit: 'text-amber-400',
};

function renderEvent(event: AgentEvent): ReactNode {
  const Icon = EVENT_ICONS[event.type] || Bot;
  const colorClass = EVENT_COLORS[event.type] || 'text-nexus-text-muted';
  const toolName = String(event.tool_name ?? event.type);
  const appId = String(event.app_id ?? '');
  const error = String(event.error ?? '');
  const reason = String(event.reason ?? '');
  const hasData = !!event.data && typeof event.data === 'object';
  const summary = String(event.summary ?? '');

  switch (event.type) {
    case 'tool_executed':
      return (
        <div className="flex items-start gap-2.5">
          <Icon className={`w-4 h-4 mt-0.5 ${colorClass}`} />
          <div className="flex-1 min-w-0">
            <ToolName name={toolName} />
            {summary && (
              <p className="text-sm text-nexus-text-secondary mt-0.5">{summary}</p>
            )}
            {!summary && hasData && Object.keys(event.data as Record<string, unknown>).length > 0 && (
              <pre className="mt-1 text-xs text-nexus-text-secondary bg-nexus-bg-tertiary/30 rounded p-1.5 overflow-x-auto">
                {JSON.stringify(event.data, null, 2)}
              </pre>
            )}
          </div>
        </div>
      );
    case 'tool_error':
      return (
        <div className="flex items-start gap-2.5">
          <Icon className={`w-4 h-4 mt-0.5 ${colorClass}`} />
          <div className="flex-1">
            <ToolName name={toolName} />
            {error && <p className="text-sm text-nexus-text-secondary mt-0.5">{error}</p>}
          </div>
        </div>
      );
    case 'app_unavailable':
      return (
        <div className="flex items-start gap-2.5">
          <Icon className={`w-4 h-4 mt-0.5 ${colorClass}`} />
          <div className="flex-1">
            <span className="font-medium text-nexus-text capitalize">{appId || 'App'}</span>
            <span className="text-sm text-nexus-text-secondary ml-2">— {reason || 'not available'}</span>
          </div>
        </div>
      );
    case 'tool_declined':
      return (
        <div className="flex items-start gap-2.5">
          <Icon className={`w-4 h-4 mt-0.5 ${colorClass}`} />
          <div className="flex-1">
            <span className="font-medium text-nexus-text">{toolName}</span>
            <span className="text-sm text-nexus-text-secondary ml-2">— declined by you</span>
          </div>
        </div>
      );
    case 'step_limit':
      return (
        <div className="flex items-start gap-2.5">
          <Icon className={`w-4 h-4 mt-0.5 ${colorClass}`} />
          <span className="text-sm text-nexus-text-secondary">Stopped after {String(event.steps ?? '')} rounds of tool calls</span>
        </div>
      );
    case 'llm_error':
      return (
        <div className="flex items-start gap-2.5">
          <Icon className={`w-4 h-4 mt-0.5 ${colorClass}`} />
          <div className="flex-1">
            <span className="font-medium text-nexus-text">LLM request failed</span>
            {error && <span className="text-sm text-nexus-text-secondary">— {error}</span>}
          </div>
        </div>
      );
    default:
      return null;
  }
}

interface MessageProps {
  message: ChatMessage;
  onCopy?: (text: string) => void;
  /** Set only on the message whose approval is still current. */
  onApprove?: (approved: boolean) => void;
  /** Set on the last reply: ask the same question again. */
  onRetry?: () => void;
  /** Set on the last question: change it and ask again. */
  onEdit?: (text: string) => void;
  /** Set only on the message whose question cards are still current. */
  onAnswer?: (answers: QuestionAnswers) => void;
}

const numberFormat = new Intl.NumberFormat();

function usageText(usage: NonNullable<ChatMessage['usage']>): string {
  const tokens = usage.input_tokens + usage.output_tokens;
  const cached = usage.cached_tokens ? ` (${numberFormat.format(usage.cached_tokens)} cached)` : '';
  const parts = [`${usage.estimated ? '~' : ''}${numberFormat.format(tokens)} tokens${cached}`];
  if (usage.cost !== null && usage.cost !== undefined) parts.push(usage.cost < 0.01 ? '<$0.01' : `$${usage.cost.toFixed(2)}`);
  return parts.join(' · ');
}

/** What you typed: the server also keeps the attached files' text and a note about documents in the message. */
export const typedText = (content: string) => content.split("\n\nAttached file '")[0]
  .replace(/\n\n\(I attached [^\n]*\. They're searchable in this chat\.\)$/, '')
  .replace(/\n\n📎 .*$/s, '').trim();

export function Message({ message, onCopy, onApprove, onRetry, onEdit, onAnswer }: MessageProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const isUser = message.role === 'user';
  const mentionLabels = useMentionLabels(isUser ? message.content : '');
  const running = message.status === 'running';
  const pending = message.status === 'needs_approval' ? message.pendingAction : undefined;
  const asking = message.status === 'needs_input' ? message.pendingQuestion : undefined;
  const answered = (message.events ?? []).filter(e => e.type === 'user_answered')
    .map(e => e.answers as QuestionAnswers);
  const visibleEvents = (message.events ?? []).filter(e => e.type !== 'intent_no_match' && e.type !== 'user_answered');

  return (
    <div
      className={cn(
        'group/message flex gap-3 animate-slide-up',
        isUser && 'flex-row-reverse'
      )}
      data-message-id={message.id}
    >
      {!isUser && (
        <Logo className="mt-0.5 h-7 w-7 shrink-0" />
      )}

      <div
        className={cn(
          // Your messages hug the right edge next to your avatar; replies take the width they need.
          isUser ? 'max-w-[85%] min-w-0 text-right' : 'flex-1 min-w-0'
        )}
      >
        <div
          className={cn(
            'inline-block max-w-full text-left',
            isUser
              ? 'rounded-2xl rounded-br-md bg-nexus-bg-tertiary px-4 py-2.5 text-nexus-text'
              : 'w-full pt-0.5'
          )}
        >
          {message.activity && message.activity.length > 0 && (
            <ul className="mb-1.5 space-y-1 text-xs" aria-label="Tool activity">
              {message.activity.map((a, i) => (
                <li key={i} className="flex items-center gap-1.5 text-nexus-text-secondary">
                  {a.state === 'running' && <Loader2 className="w-3.5 h-3.5 animate-spin text-nexus-accent-text" />}
                  {a.state === 'ok' && <CheckCircle2 className="w-3.5 h-3.5 text-green-400" />}
                  {a.state === 'failed' && <AlertCircle className="w-3.5 h-3.5 text-red-400" />}
                  <ToolName name={a.tool} />
                  {a.summary && <span className="truncate text-nexus-text-muted">— {a.summary}</span>}
                </li>
              ))}
            </ul>
          )}
          {answered.map((answers, i) => <AnsweredQuestions key={i} answers={answers} />)}
          {running && !message.content ? (
            <div className="flex items-center gap-2 text-sm text-nexus-text-secondary">
              <span>Nexus is thinking</span>
              <span className="thinking-dots text-nexus-text-secondary/50"><span>.</span><span>.</span><span>.</span></span>
            </div>
          ) : !pending && !asking && (editing ? (
            <form className="space-y-2 min-w-[16rem]" onSubmit={(e) => { e.preventDefault(); setEditing(false); onEdit?.(draft); }}>
              <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} aria-label="Edit message" autoFocus
                className="w-full rounded-lg p-2 text-sm text-nexus-text bg-nexus-bg-secondary border border-nexus-border focus:outline-none focus:ring-2 focus:ring-nexus-accent/25" />
              <div className="flex justify-end gap-2">
                <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
                <Button type="submit" size="sm" variant="secondary" disabled={!draft.trim()}>Send</Button>
              </div>
            </form>
          ) : isUser ? (
            <div className="whitespace-pre-wrap break-words text-sm"><MentionText text={typedText(message.content)} labels={mentionLabels} /></div>
          ) : (
            <Markdown text={message.content} />
          ))}
          {!isUser && !running && message.citations && message.citations.length > 0 && (
            <Sources citations={message.citations} />
          )}
          {asking && (onAnswer
            ? <QuestionCard questions={asking.questions} onSubmit={onAnswer} />
            : <p className="text-xs text-nexus-text-muted">These questions are no longer waiting.</p>)}
          {pending && (
            <div className="mt-2 space-y-3 rounded-xl border border-nexus-warning/30 bg-nexus-bg-secondary p-4 text-sm shadow-surface sm:max-w-lg" role="group" aria-label="Approval needed">
              <div className="flex items-start gap-2 font-medium text-nexus-text">
                <ShieldQuestion className="w-4 h-4 mt-0.5 text-amber-400 flex-shrink-0" />
                <span>Nexus wants to use <ToolName name={pending.tool} /></span>
              </div>
              <ApprovalDetails arguments={pending.arguments} />
              {onApprove ? (
                <div className="flex items-center gap-2">
                  <Button size="sm" onClick={() => onApprove(true)}>Approve</Button>
                  <Button size="sm" variant="secondary" onClick={() => onApprove(false)}>Deny</Button>
                </div>
              ) : (
                <p className="text-xs text-nexus-text-muted">This request is no longer waiting.</p>
              )}
            </div>
          )}
        </div>

        <div className={cn('mt-1.5 flex items-center gap-1 text-xs text-nexus-text-muted transition-opacity',
          'opacity-60 group-hover/message:opacity-100 focus-within:opacity-100', isUser && 'justify-end')}>
          <time dateTime={message.timestamp} className={cn(isUser && 'ml-auto')}>
            {formatRelativeTime(message.timestamp)}
          </time>
          {!isUser && message.usage && (message.usage.input_tokens + message.usage.output_tokens > 0) && (
            <span title="Tokens this reply used (input + output)">{usageText(message.usage)}</span>
          )}
          {onRetry && (
            <Tooltip content="Ask again">
              <Button variant="ghost" size="sm" className="h-6 w-6 px-0" onClick={onRetry} aria-label="Retry">
                <RotateCcw className="w-3.5 h-3.5" />
              </Button>
            </Tooltip>
          )}
          {onEdit && !editing && (
            <Tooltip content="Edit and ask again">
              <Button variant="ghost" size="sm" className="h-6 w-6 px-0" aria-label="Edit message"
                onClick={() => { setDraft(typedText(message.content)); setEditing(true); }}>
                <Pencil className="w-3.5 h-3.5" />
              </Button>
            </Tooltip>
          )}
          {!isUser && message.content && (
            <Tooltip content="Copy message">
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 px-0"
                onClick={() => onCopy?.(message.content)}
                aria-label="Copy message"
              >
                <Copy className="w-3.5 h-3.5" />
              </Button>
            </Tooltip>
          )}
        </div>
        {isUser && message.files && message.files.length > 0 && (
          <div className="mt-1.5 flex flex-wrap justify-end gap-2">{message.files.map(file => <FileChip key={file.id} file={file} />)}</div>
        )}
        {/* Where the answer came from (tool calls), then anything else that happened (errors, declines) */}
        {!isUser && <MadeFiles events={visibleEvents.filter(e => e.type === 'tool_executed')} />}
        {!isUser && <ToolSources events={visibleEvents.filter(e => e.type === 'tool_executed')} />}
        {!isUser && visibleEvents.some(e => e.type !== 'tool_executed') && (
          <div className="mt-2 space-y-1.5 pl-1">
            {visibleEvents.filter(e => e.type !== 'tool_executed').map((event, idx) => (
              <div key={idx} className="flex items-start gap-2 text-xs">
                {renderEvent(event)}
              </div>
            ))}
          </div>
        )}
      </div>

    </div>
  );
}
