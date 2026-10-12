import { useEffect, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { mcpService } from '../../services/mcp';
import { ragService } from '../../services/rag';

/** What to suggest for well-known apps; others get a general "what can you do" prompt. */
const APP_PROMPTS: [RegExp, string][] = [
  [/github/i, 'List my open GitHub pull requests'],
  [/gitlab/i, 'List my open GitLab merge requests'],
  [/notion/i, 'Summarise my most recent Notion pages'],
  [/linear/i, 'What Linear issues are assigned to me?'],
  [/atlassian|jira|confluence/i, 'List my open Jira issues'],
  [/slack/i, 'Summarise today\'s messages in Slack'],
  [/stripe/i, 'Show this week\'s Stripe payments'],
  [/figma/i, 'List my recent Figma files'],
  [/supabase/i, 'List my Supabase projects'],
  [/vercel/i, 'Show my latest Vercel deployments'],
  [/airtable/i, 'List my Airtable bases'],
];

const MAX = 4;

/** Starter prompts for an empty chat, from the connected apps and the first ready document. */
export function starterPrompts(apps: string[], documentName: string | null): string[] {
  const prompts = apps.map(app => APP_PROMPTS.find(([pattern]) => pattern.test(app))?.[1] ?? `What can you do with ${app}?`);
  if (documentName) prompts.push(`Summarise ${documentName}`);
  if (prompts.length === 0) prompts.push('What can you help me with?');
  // Keep the document prompt when there are many apps.
  return prompts.length > MAX && documentName ? [...prompts.slice(0, MAX - 1), prompts[prompts.length - 1]] : prompts.slice(0, MAX);
}

export function StarterPrompts({ onPick }: { onPick: (text: string) => void }) {
  const [prompts, setPrompts] = useState<string[]>([]);

  useEffect(() => {
    let alive = true;
    const apps = mcpService.list()
      .then(servers => servers.filter(s => s.enabled && s.status === 'connected').map(s => s.name))
      .catch(() => [] as string[]);
    const document = ragService.collections()
      .then(async libraries => {
        const library = libraries.find(l => l.kind === 'library' && l.ready > 0);
        if (!library) return null;
        return (await ragService.documents(library.id)).find(d => d.status === 'ready')?.name ?? null;
      })
      .catch(() => null);
    void Promise.all([apps, document]).then(([names, doc]) => {
      if (alive) setPrompts(starterPrompts([...new Set(names)], doc));
    });
    return () => { alive = false; };
  }, []);

  if (prompts.length === 0) return null;
  return (
    <div className="mt-7 flex w-full max-w-xl flex-wrap justify-center gap-2">
      {prompts.map(prompt => (
        <button key={prompt} type="button" onClick={() => onPick(prompt)}
          className="group flex w-full items-start gap-2.5 rounded-lg sm:w-[calc(50%-0.25rem)] border border-nexus-border bg-nexus-bg-secondary px-3.5 py-3 text-left text-[13px] text-nexus-text-secondary shadow-surface transition-colors hover:border-nexus-border-hover hover:bg-nexus-bg-tertiary hover:text-nexus-text">
          <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-nexus-text-muted transition-colors group-hover:text-nexus-accent-text" aria-hidden />
          <span>{prompt}</span>
        </button>
      ))}
    </div>
  );
}
