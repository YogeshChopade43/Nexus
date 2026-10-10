import { useRef, useEffect, useImperativeHandle, forwardRef } from 'react';
import { Bot } from 'lucide-react';
import { ScrollArea } from '../ui/ScrollArea';
import { Message } from './Message';
import { StarterPrompts } from './StarterPrompts';
import type { ChatMessage } from '../../types/chat';

export interface MessageListProps {
  messages: ChatMessage[];
  onCopy?: (text: string) => void;
  onApprove?: (approved: boolean) => void;
  onRetry?: () => void;
  onEdit?: (text: string) => void;
  /** Offer starter prompts in an empty chat; picking one sends it. */
  onPickPrompt?: (text: string) => void;
  autoScroll?: boolean;
}

export interface MessageListRef {
  scrollToBottom: () => void;
  scrollToTop: () => void;
}

export const MessageList = forwardRef<MessageListRef, MessageListProps>(
  ({ messages, onCopy, onApprove, onRetry, onEdit, onPickPrompt, autoScroll = true }, ref) => {
    const lastUser = messages.map(m => m.role).lastIndexOf('user');
    const lastAssistant = messages.map(m => m.role).lastIndexOf('assistant');
    const scrollAreaRef = useRef<HTMLDivElement>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);

    useImperativeHandle(ref, () => ({
      scrollToBottom: () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
      },
      scrollToTop: () => {
        scrollAreaRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
      },
    }));

    useEffect(() => {
      if (autoScroll) {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
      }
    }, [messages, autoScroll]);

    if (messages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[400px] text-nexus-text-muted">
        <div className="w-20 h-20 rounded-full bg-nexus-accent-dim flex items-center justify-center mb-6">
          <Bot className="w-10 h-10 text-nexus-accent/70" />
        </div>
        <h3 className="text-xl font-semibold text-nexus-text mb-2">How can I help?</h3>
        <p className="text-sm text-nexus-text-secondary max-w-sm text-center">
          Ask anything, or work with your connected apps and documents. Try one of these:
        </p>
        {onPickPrompt && <StarterPrompts onPick={onPickPrompt} />}
      </div>
    );
    }

    return (
      <ScrollArea className="h-full" ref={scrollAreaRef}>
        <div className="flex flex-col gap-4 pb-4" role="log" aria-live="polite" aria-label="Chat messages">
          {messages.map((message, index) => (
            <Message
              key={message.id}
              message={message}
              onCopy={onCopy}
              onApprove={index === messages.length - 1 ? onApprove : undefined}
              onRetry={index === lastAssistant && index > lastUser && messages[index].status !== 'needs_approval' ? onRetry : undefined}
              onEdit={index === lastUser ? onEdit : undefined}
            />
          ))}
          <div ref={messagesEndRef} />
        </div>
      </ScrollArea>
    );
  }
);

MessageList.displayName = 'MessageList';
