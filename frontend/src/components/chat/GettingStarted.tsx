import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AppWindow, BellRing, CheckCircle2, FileText, Mail, Newspaper, Play, X, type LucideIcon } from 'lucide-react';
import { api } from '../../services/api';
import { integrationService } from '../../services/integrations';
import { mcpService } from '../../services/mcp';
import { ragService } from '../../services/rag';
import { cn } from '../../lib/utils';

const HIDDEN_KEY = 'nexus.gettingStarted.hidden';

function readHidden(): boolean {
  try { return localStorage.getItem(HIDDEN_KEY) === '1'; } catch { return false; }
}

interface Goal {
  id: string;
  icon: LucideIcon;
  title: string;
  detail: string;
  setup: string;  // where to set it up
  prompt: string;  // what "Try it" asks
}

const GOALS: Goal[] = [
  { id: 'phone', icon: BellRing, title: 'Reminders on my phone', detail: 'Link Telegram; reminders and alerts arrive even when Nexus is closed.',
    setup: '/servers?connect=telegram', prompt: 'Remind me every day at 9 pm to take my medicines, on my phone' },
  { id: 'email', icon: Mail, title: 'Help with my email', detail: 'Connect Gmail or any email; Nexus sorts your inbox and drafts replies.',
    setup: '/servers?connect=google', prompt: 'Triage my unread email: what needs a reply? Draft the replies' },
  { id: 'docs', icon: FileText, title: 'Answers from my documents', detail: 'Upload PDFs, Word or Excel files; answers cite the page they came from.',
    setup: '/knowledge', prompt: 'What are the key points in my documents?' },
  { id: 'apps', icon: AppWindow, title: 'Work with my apps', detail: 'GitHub, Notion, Linear, Stripe and more from the Marketplace.',
    setup: '/servers', prompt: 'What can you do with my apps? Give me three useful examples.' },
  { id: 'briefing', icon: Newspaper, title: 'Morning briefing', detail: 'Meetings, important email and app updates, every morning on your phone.',
    setup: '/dashboard', prompt: 'Give me a quick briefing of my day from my apps' },
];

/** First run: "What do you want Nexus for?" Each goal links to its setup, then offers to try it. */
export function GettingStarted({ hasLLM, onTry }: { hasLLM: boolean; onTry?: (prompt: string) => void }) {
  const [hidden, setHidden] = useState(readHidden);
  const [ready, setReady] = useState<Record<string, boolean> | null>(null);

  useEffect(() => {
    if (hidden) return;
    const quietly = <T,>(promise: Promise<T>, fallback: T) => promise.catch(() => fallback);
    void Promise.all([
      quietly(integrationService.list(), []),
      quietly(mcpService.list(), []),
      quietly(ragService.collections(), []),
      quietly(api.get<{ enabled: boolean }>('/api/briefing'), { enabled: false }),
    ]).then(([integrations, servers, libraries, briefing]) => {
      const linked = (kinds: string[]) => integrations.some(i => kinds.includes(i.kind) && i.status === 'connected');
      setReady({
        phone: linked(['telegram', 'slack', 'discord']),
        email: linked(['google', 'email']),
        docs: libraries.some(l => l.kind === 'library' && l.ready > 0),
        apps: servers.some(s => s.enabled && s.status === 'connected'),
        briefing: briefing.enabled,
      });
    });
  }, [hidden]);

  if (hidden || ready === null) return null;

  const hide = () => {
    try { localStorage.setItem(HIDDEN_KEY, '1'); } catch { /* private mode: hide for this visit only */ }
    setHidden(true);
  };

  return (
    <section aria-label="Getting started" className="mx-auto mt-8 w-full max-w-2xl text-left">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-[13px] font-semibold text-nexus-text">What do you want Nexus for?</h2>
        <button type="button" onClick={hide} aria-label="Hide getting started" className="text-nexus-text-muted hover:text-nexus-text">
          <X className="h-4 w-4" />
        </button>
      </div>
      {!hasLLM && (
        <Link to="/settings?tab=ai"
          className="mb-3 flex items-center gap-2 rounded-lg border border-nexus-accent/40 bg-nexus-accent/5 p-3 text-[13px] text-nexus-text hover:no-underline">
          <span className="font-medium">First, add an AI provider</span>
          <span className="text-nexus-text-secondary">: Nexus needs a model to think with (OpenAI, OpenRouter, Anthropic, or Ollama offline).</span>
        </Link>
      )}
      <ul className="grid gap-2 sm:grid-cols-2">
        {GOALS.map(goal => {
          const done = ready[goal.id];
          const Icon = goal.icon;
          return (
            <li key={goal.id} aria-label={goal.title}
              className={cn('flex gap-3 rounded-xl border bg-nexus-bg-secondary p-3 shadow-surface',
                done ? 'border-nexus-success/30' : 'border-nexus-border')}>
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-nexus-border bg-nexus-bg-tertiary text-nexus-text-secondary">
                <Icon className="h-4 w-4" aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-1.5 text-[13px] font-medium text-nexus-text">
                  {goal.title}
                  {done && <CheckCircle2 className="h-3.5 w-3.5 text-nexus-success" aria-label="ready" />}
                </p>
                <p className="mt-0.5 text-xs text-nexus-text-muted">{goal.detail}</p>
                <div className="mt-2">
                  {done && onTry ? (
                    <button type="button" onClick={() => onTry(goal.prompt)}
                      className="inline-flex items-center gap-1 text-xs font-medium text-nexus-accent-text hover:underline">
                      <Play className="h-3 w-3" aria-hidden /> Try it
                    </button>
                  ) : !done ? (
                    <Link to={goal.setup} className="text-xs font-medium">Set up →</Link>
                  ) : null}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
