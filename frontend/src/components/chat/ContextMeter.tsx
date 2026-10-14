import { useEffect, useRef, useState } from 'react';
import { api } from '../../services/api';
import { cn } from '../../lib/utils';
import type { ChatMessage } from '../../types/chat';

interface Window {
  tokens: number | null;
  source: string | null;
  model: string;
}

const number = new Intl.NumberFormat();
const compact = new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 });

const money = (dollars: number) => (dollars < 0.01 ? '<$0.01' : `$${dollars.toFixed(2)}`);

/** Colour by how full: violet with room to spare, amber when filling, red when nearly full. */
function tone(percent: number) {
  return percent >= 85 ? 'text-nexus-danger' : percent >= 60 ? 'text-nexus-warning' : 'text-nexus-accent-text';
}

/** How full this chat's context window is: the biggest prompt the last reply sent, against the model's window. */
export function ContextMeter({ messages, providerId }: { messages: ChatMessage[]; providerId: number | null }) {
  const [window, setWindow] = useState<Window | null>(null);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    api.get<Window>('/api/llm/context-window', providerId !== null ? { provider_id: String(providerId) } : undefined)
      .then(found => { if (alive) setWindow(found); })
      .catch(() => { if (alive) setWindow(null); });
    return () => { alive = false; };
  }, [providerId]);

  useEffect(() => {
    if (!open) return;
    const outside = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const escape = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', outside);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('mousedown', outside); document.removeEventListener('keydown', escape); };
  }, [open]);

  const last = [...messages].reverse().find(m => m.role === 'assistant' && m.usage?.context_tokens);
  const used = last?.usage?.context_tokens ?? 0;
  const approx = last?.usage?.estimated ? '≈' : '';
  const size = window?.tokens ?? null;
  const percent = size ? Math.min(100, Math.round((used / size) * 100)) : null;
  const shown = percent === 0 && used > 0 ? '<1%' : `${percent}%`;  // a short chat isn't "empty"
  const label = percent !== null ? `Context window: ${percent}% used` : `Context window: ${approx}${number.format(used)} tokens used`;
  const circumference = 2 * Math.PI * 6;

  // What the whole chat has cost: every reply's tokens, and its price when the model has one set.
  const replies = messages.filter(m => m.role === 'assistant' && m.usage);
  const chatTokens = replies.reduce((sum, m) => sum + m.usage!.input_tokens + m.usage!.output_tokens, 0);
  const priced = replies.filter(m => typeof m.usage!.cost === 'number');
  const cost = priced.length ? money(priced.reduce((sum, m) => sum + m.usage!.cost!, 0)) : null;
  const unpriced = replies.length - priced.length;

  return (
    <div ref={ref} className="relative flex items-center">
      <button type="button" aria-label={label} title={label} aria-expanded={open} onClick={() => setOpen(o => !o)}
        className="flex h-8 items-center gap-1.5 rounded-md px-2 text-xs tabular-nums text-nexus-text-secondary transition-colors hover:bg-nexus-bg-tertiary hover:text-nexus-text">
        <svg viewBox="0 0 16 16" className="h-4 w-4 -rotate-90" aria-hidden>
          <circle cx="8" cy="8" r="6" fill="none" strokeWidth="2.5" className="stroke-nexus-border-hover" />
          {percent !== null && (
            <circle cx="8" cy="8" r="6" fill="none" strokeWidth="2.5" strokeLinecap="round"
              className={cn('stroke-current transition-[stroke-dashoffset] duration-500', tone(percent))}
              strokeDasharray={circumference} strokeDashoffset={circumference * (1 - percent / 100)} />
          )}
        </svg>
        <span className="hidden sm:inline">{percent !== null ? shown : `${approx}${compact.format(used)}`}</span>
      </button>
      {cost && (
        <span title={`This chat has cost ${cost} so far`}
          className="border-l border-nexus-border pl-2 pr-1 text-xs tabular-nums text-nexus-text-secondary">{cost}</span>
      )}

      {open && (
        <div role="dialog" aria-label="Context window"
          className="absolute right-0 top-full z-30 mt-2 w-72 space-y-3 rounded-lg border border-nexus-border bg-nexus-bg-secondary p-4 shadow-pop animate-fade-in">
          <div className="flex items-baseline justify-between gap-2">
            <p className="text-[13px] font-semibold text-nexus-text">Context window</p>
            {window?.model && <p className="truncate text-[11px] text-nexus-text-muted" title={window.model}>{window.model}</p>}
          </div>
          {percent !== null && size ? (
            <>
              <div role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} aria-label="Context used"
                className="h-1.5 overflow-hidden rounded-full bg-nexus-bg-tertiary">
                <div className={cn('h-full rounded-full bg-current transition-[width] duration-500', tone(percent))} style={{ width: `${percent}%` }} />
              </div>
              <p className="text-xs tabular-nums text-nexus-text-secondary">
                {approx}{number.format(used)} of {number.format(size)} tokens <span className={tone(percent)}>· {shown}</span>
              </p>
              <p className="text-xs text-nexus-text-muted">
                {used === 0 ? 'Fills up as you chat.'
                  : percent >= 85 ? 'Nearly full. Older messages are summarised to make room, but details can be lost: start a new chat for a fresh context.'
                  : percent >= 60 ? 'Getting full. Older messages are summarised automatically to make room.'
                  : 'Plenty of room.'}
              </p>
            </>
          ) : (
            <p className="text-xs text-nexus-text-secondary">
              {approx}{number.format(used)} tokens used. This model&apos;s window size isn&apos;t known, so the percentage can&apos;t be shown.
            </p>
          )}
          {replies.length > 0 && (
            <div className="space-y-1 border-t border-nexus-border pt-3">
              <p className="text-xs tabular-nums text-nexus-text">
                This chat: {number.format(chatTokens)} tokens{cost ? ` · ${cost}` : ''}
              </p>
              {unpriced > 0 && (
                <p className="text-[11px] text-nexus-text-muted">
                  {cost ? `${unpriced} ${unpriced === 1 ? 'reply has' : 'replies have'} no price, so the cost is a minimum. `
                    : 'No cost shown: '}Set model prices on the Dashboard.
                </p>
              )}
            </div>
          )}
          <p className="border-t border-nexus-border pt-3 text-[11px] leading-relaxed text-nexus-text-muted">
            Measured from the last reply: instructions, your apps&apos; tools, document passages and the conversation sent to the model.
            {approx && ' Streamed replies are estimated (~4 characters per token).'}
            {window?.source === 'openrouter' && ' Window size from OpenRouter.'}
          </p>
        </div>
      )}
    </div>
  );
}
