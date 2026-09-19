import { useState, useRef, useCallback, useEffect, KeyboardEvent } from 'react';
import { Button } from '../ui/Button';
import { Send, Sparkles } from 'lucide-react';
import { Textarea } from '../ui/Input';

interface ComposerProps {
  onSend: (content: string) => void;
  disabled?: boolean;
  placeholder?: string;
  maxLength?: number;
}

export function Composer({ onSend, disabled, placeholder = 'Message Agent...', maxLength = 4000 }: ComposerProps) {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }, []);

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed) return;
    if (disabled) return;

    onSend(trimmed);
    setValue('');
    textareaRef.current?.focus();
  };

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const charsRemaining = maxLength - value.length;

  return (
    <div className="bg-nexus-bg-secondary border-t-nexus-border border-t p-4">
      <div className="flex items-end gap-2">
        <div className="flex-1 relative">
          <Textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            rows={1}
            className="resize-none pr-12 min-h-[44px] max-h-[160px] bg-nexus-bg-tertiary border-nexus-border focus:border-nexus-accent focus:ring-nexus-accent"
            aria-label="Message input"
            aria-describedby={charsRemaining < 100 ? 'char-count' : undefined}
          />
          {charsRemaining < 100 && (
            <span id="char-count" className="absolute bottom-2 right-10 text-xs text-nexus-text-muted">
              {charsRemaining}
            </span>
          )}
        </div>

        <Button
          onClick={handleSubmit}
          disabled={disabled || !value.trim()}
          size="sm"
          className="h-10 w-10 p-0 flex-shrink-0"
          aria-label="Send message"
        >
          <Send className="w-5 h-5" />
        </Button>
      </div>

      <div className="flex items-center justify-between mt-2 text-xs text-nexus-text-muted">
        <span>Press Enter to send, Shift+Enter for new line</span>
        <span className="flex items-center gap-2">
          <Sparkles className="w-3.5 h-3.5" />
          <span>Powered by Nexus AI</span>
        </span>
      </div>
    </div>
  );
}
