import {
  Braces, Clock, Code2, Columns3, GitFork, Globe, Repeat, Send, Sparkles, Workflow, Wrench, Zap, type LucideIcon,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import type { WorkflowNodeType } from '../../types/workflow';

/** Each step type's icon, and a colour family per kind: start (amber), AI (violet), logic (blue), data (teal), apps (zinc). */
const KINDS: Record<WorkflowNodeType, { icon: LucideIcon; tone: string }> = {
  trigger: { icon: Zap, tone: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 ring-amber-500/25' },
  action: { icon: Wrench, tone: 'bg-zinc-500/10 text-zinc-600 dark:text-zinc-300 ring-zinc-500/25' },
  llm: { icon: Sparkles, tone: 'bg-violet-500/10 text-violet-600 dark:text-violet-400 ring-violet-500/25' },
  condition: { icon: GitFork, tone: 'bg-blue-500/10 text-blue-600 dark:text-blue-400 ring-blue-500/25' },
  loop: { icon: Repeat, tone: 'bg-blue-500/10 text-blue-600 dark:text-blue-400 ring-blue-500/25' },
  parallel: { icon: Columns3, tone: 'bg-blue-500/10 text-blue-600 dark:text-blue-400 ring-blue-500/25' },
  delay: { icon: Clock, tone: 'bg-blue-500/10 text-blue-600 dark:text-blue-400 ring-blue-500/25' },
  transform: { icon: Braces, tone: 'bg-teal-500/10 text-teal-600 dark:text-teal-400 ring-teal-500/25' },
  code: { icon: Code2, tone: 'bg-teal-500/10 text-teal-600 dark:text-teal-400 ring-teal-500/25' },
  output: { icon: Send, tone: 'bg-teal-500/10 text-teal-600 dark:text-teal-400 ring-teal-500/25' },
  http: { icon: Globe, tone: 'bg-sky-500/10 text-sky-600 dark:text-sky-400 ring-sky-500/25' },
  workflow: { icon: Workflow, tone: 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 ring-indigo-500/25' },
};

/** A step type's icon in a small tinted tile (decorative: the step's name says what it is). */
export function NodeTile({ type, size = 'md', className }: { type: WorkflowNodeType; size?: 'sm' | 'md'; className?: string }) {
  const { icon: Icon, tone } = KINDS[type] ?? KINDS.action;
  return (
    <span aria-hidden className={cn('inline-flex shrink-0 items-center justify-center rounded-md ring-1 ring-inset', tone,
      size === 'sm' ? 'h-5 w-5' : 'h-6 w-6', className)}>
      <Icon className={size === 'sm' ? 'h-3 w-3' : 'h-3.5 w-3.5'} />
    </span>
  );
}
