import { useRef, useEffect, useImperativeHandle, forwardRef } from 'react';
import { ScrollArea } from '../ui/ScrollArea';
import { Message } from './Message';
import type { ChatMessage } from '../../types/chat';

export interface MessageListProps {
  messages: ChatMessage[];
  onCopy?: (text: string) => void;
  autoScroll?: boolean;
}

export interface MessageListRef {
  scrollToBottom: () => void;
  scrollToTop: () => void;
}

export const MessageList = forwardRef<MessageListRef, MessageListProps>(
  ({ messages, onCopy, autoScroll = true }, ref) => {
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
          <div className="w-16 h-16 rounded-full bg-nexus-accent-dim flex items-center justify-center mb-4">
            <svg className="w-8 h-8 text-nexus-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
          </div>
          <h3 className="text-lg font-medium text-nexus-text mb-1">No messages yet</h3>
          <p className="text-sm">Start a conversation by typing a message below</p>
        </div>
      );
    }

    return (
      <ScrollArea className="h-full" ref={scrollAreaRef}>
        <div className="flex flex-col gap-4 pb-4" role="log" aria-live="polite" aria-label="Chat messages">
          {messages.map((message) => (
            <Message
              key={message.id}
              message={message}
              onCopy={onCopy}
            />
          ))}
          <div ref={messagesEndRef} />
        </div>
      </ScrollArea>
    );
  }
);

MessageList.displayName = 'MessageList';
