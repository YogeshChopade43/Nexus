import { useRef, useEffect, useImperativeHandle, forwardRef, type ReactNode } from 'react';
import { Logo } from '../layout/Sidebar';
import { ScrollArea } from '../ui/ScrollArea';
import { Message } from './Message';
import { StarterPrompts } from './StarterPrompts';
import type { ChatMessage, QuestionAnswers } from '../../types/chat';

export interface MessageListProps {
  messages: ChatMessage[];
  onCopy?: (text: string) => void;
  onApprove?: (approved: boolean) => void;
  onRetry?: () => void;
  onEdit?: (text: string) => void;
  onAnswer?: (answers: QuestionAnswers) => void;
  /** Offer starter prompts in an empty chat; picking one sends it. */
  onPickPrompt?: (text: string) => void;
  /** Shown under the welcome in an empty chat (the getting-started checklist). */
  intro?: ReactNode;
  autoScroll?: boolean;
}

export interface MessageListRef {
  scrollToBottom: () => void;
  scrollToTop: () => void;
}

export const MessageList = forwardRef<MessageListRef, MessageListProps>(
  ({ messages, onCopy, onApprove, onRetry, onEdit, onAnswer, onPickPrompt, intro, autoScroll = true }, ref) => {
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
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex min-h-full w-full max-w-2xl flex-col items-center justify-center px-4 py-10 text-center">
          <Logo className="mb-5 h-11 w-11 rounded-xl" />
          <h3 className="text-2xl font-semibold tracking-tight text-nexus-text">How can I help?</h3>
          <p className="mt-2 max-w-md text-sm text-nexus-text-secondary">
            Ask anything, or work with your connected apps and documents. Try one of these:
          </p>
          {onPickPrompt && <StarterPrompts onPick={onPickPrompt} />}
          {intro}
        </div>
      </div>
    );
    }

    return (
      <ScrollArea className="flex-1" ref={scrollAreaRef}>
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6 lg:px-6" role="log" aria-live="polite" aria-label="Chat messages">
          {messages.map((message, index) => (
            <Message
              key={message.id}
              message={message}
              onCopy={onCopy}
              onApprove={index === messages.length - 1 ? onApprove : undefined}
              onAnswer={index === messages.length - 1 ? onAnswer : undefined}
              onRetry={index === lastAssistant && index > lastUser && !['needs_approval', 'needs_input'].includes(messages[index].status ?? '') ? onRetry : undefined}
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
