import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, Circle, X } from 'lucide-react';
import { chatService } from '../../services/chat';
import { mcpService } from '../../services/mcp';

const HIDDEN_KEY = 'nexus.gettingStarted.hidden';

function readHidden(): boolean {
  try { return localStorage.getItem(HIDDEN_KEY) === '1'; } catch { return false; }
}

/** First-run checklist: add an AI provider, connect an app, try a prompt. Hides itself when all are done. */
export function GettingStarted({ hasLLM }: { hasLLM: boolean }) {
  const [hidden, setHidden] = useState(readHidden);
  const [appConnected, setAppConnected] = useState<boolean | null>(null);
  const [chatted, setChatted] = useState<boolean | null>(null);

  useEffect(() => {
    if (hidden) return;
    mcpService.list().then(s => setAppConnected(s.some(x => x.enabled && x.status === 'connected'))).catch(() => setAppConnected(false));
    chatService.listSessions().then(s => setChatted(s.length > 0)).catch(() => setChatted(false));
  }, [hidden]);

  if (hidden || appConnected === null || chatted === null) return null;
  const steps = [
    { done: hasLLM, label: 'Add an AI provider', detail: 'Nexus needs a model to think with.', to: '/settings?tab=ai' },
    { done: appConnected, label: 'Connect an app', detail: 'Notion, GitHub, Linear and more, from the Marketplace.', to: '/servers' },
    { done: chatted, label: 'Try a prompt', detail: 'Pick a suggestion below, or ask anything.', to: null },
  ];
  const done = steps.filter(s => s.done).length;
  if (done === steps.length) return null;

  const hide = () => {
    try { localStorage.setItem(HIDDEN_KEY, '1'); } catch { /* private mode: hide for this visit only */ }
    setHidden(true);
  };

  return (
    <section aria-label="Getting started" className="mx-auto mt-4 w-full max-w-xl rounded-xl border border-nexus-border bg-nexus-bg-secondary p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-nexus-text">Getting started</h2>
        <span className="flex items-center gap-2 text-xs text-nexus-text-muted">
          {done} of {steps.length} done
          <button type="button" onClick={hide} aria-label="Hide getting started" className="hover:text-nexus-text">
            <X className="w-4 h-4" />
          </button>
        </span>
      </div>
      <ol className="mt-3 space-y-2">
        {steps.map(step => {
          const Icon = step.done ? CheckCircle2 : Circle;
          const body = (
            <>
              <Icon className={step.done ? 'w-5 h-5 text-green-500 flex-shrink-0' : 'w-5 h-5 text-nexus-text-muted flex-shrink-0'} aria-hidden />
              <span className="min-w-0">
                <span className={step.done ? 'block text-sm text-nexus-text-muted line-through' : 'block text-sm font-medium text-nexus-text'}>
                  {step.label}
                </span>
                {!step.done && <span className="block text-xs text-nexus-text-secondary">{step.detail}</span>}
              </span>
            </>
          );
          return (
            <li key={step.label}>
              {step.to && !step.done
                ? <Link to={step.to} className="flex items-start gap-2.5 rounded-lg p-1.5 -m-1.5 hover:bg-nexus-bg-tertiary">{body}</Link>
                : <div className="flex items-start gap-2.5">{body}</div>}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
