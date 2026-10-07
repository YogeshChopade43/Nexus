import { cn, formatRelativeTime } from '../../lib/utils';
import { Copy, Bot, AlertCircle, CheckCircle2, Info } from 'lucide-react';
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
};

const EVENT_COLORS: Record<string, string> = {
  tool_executed: 'text-green-400',
  tool_error: 'text-red-400',
  app_unavailable: 'text-amber-400',
  intent_no_match: 'text-nexus-text-muted',
  llm_error: 'text-red-400',
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
}

export function Message({ message, onCopy }: MessageProps) {
  const isUser = message.role === 'user';
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
          'flex-1 max-w-[85%] min-w-0',
          isUser && 'text-right'
        )}
      >
        <div
          className={cn(
            'inline-block px-4 py-2.5 rounded-2xl',
            isUser
              ? 'bg-nexus-accent text-nexus-bg rounded-tr-none'
              : 'bg-nexus-bg-secondary border-nexus-border rounded-tl-none'
          )}
        >
          <div className="whitespace-pre-wrap break-words text-sm">
            {message.content}
          </div>
        </div>

        <div className="flex items-center gap-2 mt-1.5 text-xs text-nexus-text-muted">
          <time dateTime={message.timestamp}>
            {formatRelativeTime(message.timestamp)}
          </time>
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
