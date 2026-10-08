import { useState, useRef, useEffect, KeyboardEvent } from 'react';
import { Button } from '../ui/Button';
import { Paperclip, Send, Sparkles, Square, X } from 'lucide-react';
import { Textarea } from '../ui/Input';
import type { ChatAttachment } from '../../types/chat';

const MAX_FILES = 10;
const MAX_FILE_BYTES = 20_000_000;
/** Text files up to this size go straight into the message; bigger ones and PDFs into the knowledge base. */
export const INLINE_CHARS = 20_000;

type Picked = { name: string; inline: ChatAttachment } | { name: string; upload: File };

interface ComposerProps {
  onSend: (content: string, attachments: ChatAttachment[], uploads: File[]) => void;
  disabled?: boolean;
  placeholder?: string;
  maxLength?: number;
  /** While a reply is being written: show Stop instead of Send. */
  running?: boolean;
  onStop?: () => void;
}

export function Composer({ onSend, disabled, placeholder = 'Message Agent...', maxLength = 4000, running, onStop }: ComposerProps) {
  const [value, setValue] = useState('');
  const [files, setFiles] = useState<Picked[]>([]);
  const [fileError, setFileError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const addFiles = async (picked: FileList | null) => {
    setFileError(null);
    const added: Picked[] = [];
    for (const file of Array.from(picked ?? [])) {
      if (files.length + added.length >= MAX_FILES) { setFileError(`Up to ${MAX_FILES} files per message`); break; }
      if (file.size > MAX_FILE_BYTES) { setFileError(`${file.name} is larger than 20 MB`); continue; }
      if (file.name.toLowerCase().endsWith('.pdf')) { added.push({ name: file.name, upload: file }); continue; }
      const content = await file.text();
      // Text and PDF only: other binary files would just be noise to the agent.
      if (content.includes('\u0000')) { setFileError(`${file.name} isn't a text file or PDF`); continue; }
      added.push(content.length > INLINE_CHARS ? { name: file.name, upload: file } : { name: file.name, inline: { name: file.name, content } });
    }
    setFiles(prev => [...prev, ...added]);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed && files.length === 0) return;
    if (disabled) return;

    onSend(trimmed, files.flatMap(f => ('inline' in f ? [f.inline] : [])), files.flatMap(f => ('upload' in f ? [f.upload] : [])));
    setValue('');
    setFiles([]);
    setFileError(null);
    textareaRef.current?.focus();
  };

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const charsRemaining = maxLength - value.length;

  return (
    <div className="bg-nexus-bg-secondary border-t-nexus-border border-t p-4">
      {(files.length > 0 || fileError) && (
        <div className="flex flex-wrap items-center gap-2 mb-2">
          {files.map((file, i) => (
            <span key={i} className="inline-flex items-center gap-1 px-2 py-1 rounded bg-nexus-bg-tertiary text-xs text-nexus-text-secondary">
              <Paperclip className="w-3 h-3" />
              {file.name}{'upload' in file && <span className="text-nexus-text-muted"> → knowledge</span>}
              <button type="button" onClick={() => setFiles(prev => prev.filter((_, j) => j !== i))} aria-label={`Remove ${file.name}`} className="hover:text-nexus-text">
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
          {fileError && <span className="text-xs text-nexus-danger">{fileError}</span>}
        </div>
      )}
      <div className="flex items-end gap-2">
        <input ref={fileInputRef} type="file" multiple hidden accept=".pdf,.txt,.md,.csv,.json,.log,.yaml,.yml,.xml,.html,.py,.ts,.tsx,.js,.sql,text/*,application/pdf"
          onChange={(e) => void addFiles(e.target.files)} />
        <Button
          variant="ghost"
          size="sm"
          className="h-10 w-10 p-0 flex-shrink-0"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || files.length >= MAX_FILES}
          aria-label="Attach files"
          title="Attach text files or PDFs (big ones go to the knowledge base)"
        >
          <Paperclip className="w-5 h-5" />
        </Button>
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

        {running && onStop ? (
          <Button onClick={onStop} size="sm" variant="secondary" className="h-10 w-10 p-0 flex-shrink-0" aria-label="Stop" title="Stop">
            <Square className="w-4 h-4 fill-current" />
          </Button>
        ) : (
          <Button
            onClick={handleSubmit}
            disabled={disabled || (!value.trim() && files.length === 0)}
            size="sm"
            className="h-10 w-10 p-0 flex-shrink-0"
            aria-label="Send message"
          >
            <Send className="w-5 h-5" />
          </Button>
        )}
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
