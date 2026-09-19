import { cn, formatRelativeTime } from '../../lib/utils';
import { Copy } from 'lucide-react';
import { Button } from '../ui/Button';
import { Tooltip } from '../ui/Tooltip';
import type { ChatMessage } from '../../types/chat';

interface MessageProps {
  message: ChatMessage;
  onCopy?: (text: string) => void;
}

export function Message({ message, onCopy }: MessageProps) {
  const isUser = message.role === 'user';

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
