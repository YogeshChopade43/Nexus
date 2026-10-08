import { cn, formatRelativeTime } from '../../lib/utils';
import { useState } from 'react';
import { Copy, Bot, AlertCircle, CheckCircle2, Info, Ban, Loader2, ShieldQuestion, RotateCcw, Pencil, Gauge } from 'lucide-react';
import { Markdown } from './Markdown';
import { Sources } from './Sources';
import { Button } from '../ui/Button';
import { Tooltip } from '../ui/Tooltip';
import type { ChatMessage, AgentEvent } from '../../types/chat';
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
            <span className="font-medium text-nexus-text">{toolName}</span>
            {appId && <span className="text-xs text-nexus-text-muted"> ({appId})</span>}
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
            <span className="font-medium text-nexus-text">{toolName}</span>
            {error && <span className="text-sm text-nexus-text-secondary ml-2">— {error}</span>}
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
}

const numberFormat = new Intl.NumberFormat();

function usageText(usage: NonNullable<ChatMessage['usage']>): string {
  const tokens = usage.input_tokens + usage.output_tokens;
  const parts = [`${usage.estimated ? '~' : ''}${numberFormat.format(tokens)} tokens`];
  if (usage.cost !== null && usage.cost !== undefined) parts.push(usage.cost < 0.01 ? '<$0.01' : `$${usage.cost.toFixed(2)}`);
  return parts.join(' · ');
}

export function Message({ message, onCopy, onApprove, onRetry, onEdit }: MessageProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const isUser = message.role === 'user';
  const running = message.status === 'running';
  const pending = message.status === 'needs_approval' ? message.pendingAction : undefined;
  const visibleEvents = (message.events ?? []).filter(e => e.type !== 'intent_no_match');

  return (
    <div
      className={cn(
        'flex gap-3 animate-slide-up',
        isUser && 'flex-row-reverse'
      )}
      data-message-id={message.id}
    >
      {!isUser && (
        <div className="w-8 h-8 rounded-full bg-nexus-accent-dim flex items-center justify-center flex-shrink-0 mt-1">
          <svg className="w-5 h-5 text-nexus-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2a8 8 0 018 8H4a8 8 0 018-8z" />
            <path d="M12 14v4" />
            <path d="M12 22v-4" />
          </svg>
        </div>
      )}

      <div
        className={cn(
          // Your messages hug the right edge next to your avatar; replies take the width they need.
          isUser ? 'max-w-[85%] min-w-0 text-right' : 'flex-1 max-w-[85%] min-w-0'
        )}
      >
        <div
          className={cn(
            'inline-block max-w-full px-4 py-2.5 rounded-2xl text-left',
            isUser
              ? 'bg-nexus-accent text-nexus-bg rounded-tr-none'
              : 'bg-nexus-bg-secondary border-nexus-border rounded-tl-none'
          )}
        >
          {message.activity && message.activity.length > 0 && (
            <ul className="mb-1.5 space-y-1 text-xs" aria-label="Tool activity">
              {message.activity.map((a, i) => (
                <li key={i} className="flex items-center gap-1.5 text-nexus-text-secondary">
                  {a.state === 'running' && <Loader2 className="w-3.5 h-3.5 animate-spin text-nexus-accent" />}
                  {a.state === 'ok' && <CheckCircle2 className="w-3.5 h-3.5 text-green-400" />}
                  {a.state === 'failed' && <AlertCircle className="w-3.5 h-3.5 text-red-400" />}
                  <code>{a.tool}</code>
                  {a.summary && <span className="truncate text-nexus-text-muted">— {a.summary}</span>}
                </li>
              ))}
            </ul>
          )}
          {running && !message.content ? (
            <div className="flex items-center gap-2 text-sm text-nexus-text-secondary">
              <span>Nexus is thinking</span>
              <span className="thinking-dots text-nexus-text-secondary/50"><span>.</span><span>.</span><span>.</span></span>
            </div>
          ) : !pending && (editing ? (
            <form className="space-y-2 min-w-[16rem]" onSubmit={(e) => { e.preventDefault(); setEditing(false); onEdit?.(draft); }}>
              <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} aria-label="Edit message" autoFocus
                className="w-full rounded-lg p-2 text-sm text-nexus-text bg-nexus-bg-secondary border border-nexus-border focus:outline-none focus:ring-2 focus:ring-nexus-accent" />
              <div className="flex justify-end gap-2">
                <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
                <Button type="submit" size="sm" variant="secondary" disabled={!draft.trim()}>Send</Button>
              </div>
            </form>
          ) : isUser ? (
            <div className="whitespace-pre-wrap break-words text-sm">{message.content}</div>
          ) : (
            <Markdown text={message.content} />
          ))}
          {!isUser && !running && message.citations && message.citations.length > 0 && (
            <Sources citations={message.citations} />
          )}
          {pending && (
            <div className="text-sm space-y-2" role="group" aria-label="Approval needed">
              <div className="flex items-center gap-2 font-medium text-nexus-text">
                <ShieldQuestion className="w-4 h-4 text-amber-400" />
                Nexus wants to run <code className="text-nexus-accent">{pending.tool}</code>
              </div>
              {Object.keys(pending.arguments ?? {}).length > 0 && (
                <pre className="text-xs text-nexus-text-secondary bg-nexus-bg-tertiary/50 rounded p-2 overflow-x-auto max-h-48">
                  {JSON.stringify(pending.arguments, null, 2)}
                </pre>
              )}
              {onApprove ? (
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => onApprove(true)}>Approve</Button>
                  <Button size="sm" variant="secondary" onClick={() => onApprove(false)}>Deny</Button>
                </div>
              ) : (
                <p className="text-xs text-nexus-text-muted">This request is no longer waiting.</p>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 mt-1.5 text-xs text-nexus-text-muted">
          <time dateTime={message.timestamp} className={cn(isUser && 'ml-auto')}>
            {formatRelativeTime(message.timestamp)}
          </time>
          {!isUser && message.usage && (message.usage.input_tokens + message.usage.output_tokens > 0) && (
            <span title="Tokens this reply used (input + output)">{usageText(message.usage)}</span>
          )}
          {onRetry && (
            <Tooltip content="Ask again">
              <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={onRetry} aria-label="Retry">
                <RotateCcw className="w-4 h-4" />
              </Button>
            </Tooltip>
          )}
          {onEdit && !editing && (
            <Tooltip content="Edit and ask again">
              <Button variant="ghost" size="sm" className="h-6 w-6 p-0" aria-label="Edit message"
                onClick={() => { setDraft(message.content.replace(/\n\n📎 .*$/s, '')); setEditing(true); }}>
                <Pencil className="w-4 h-4" />
              </Button>
            </Tooltip>
          )}
          {!isUser && message.content && (
            <Tooltip content="Copy message">
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0"
                onClick={() => onCopy?.(message.content)}
                aria-label="Copy message"
              >
                <Copy className="w-4 h-4" />
              </Button>
            </Tooltip>
          )}
        </div>
        {/* Agent events */}
        {!isUser && visibleEvents.length > 0 && (
          <div className="mt-2 space-y-1.5 pl-1">
            {visibleEvents.map((event, idx) => (
              <div key={idx} className="flex items-start gap-2 text-xs">
                {renderEvent(event)}
              </div>
            ))}
          </div>
        )}
      </div>

      {isUser && (
        <div className="w-8 h-8 rounded-full bg-nexus-bg-tertiary flex items-center justify-center flex-shrink-0 mt-1">
          <svg className="w-5 h-5 text-nexus-text-secondary" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
            <circle cx="12" cy="7" r="4" />
          </svg>
        </div>
      )}
    </div>
  );
}
