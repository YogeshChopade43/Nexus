import type { ComponentType, ReactNode } from 'react';
import { cn } from '../../lib/utils';

/** Title, one-line description and actions at the top of every page. */
export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-nexus-text">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-[13px] leading-relaxed text-nexus-text-secondary">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** A small set of mutually exclusive options (a radio group styled as joined buttons). */
export function SegmentedControl<T extends string | number>({ options, value, onChange, label, size = 'sm', className }: {
  options: Array<{ value: T; label: ReactNode; disabled?: boolean; title?: string }>;
  value: T;
  onChange: (value: T) => void;
  label: string;
  size?: 'xs' | 'sm';
  className?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label}
      className={cn('inline-flex items-center gap-0.5 rounded-lg border border-nexus-border bg-nexus-bg-secondary p-0.5 shadow-surface', className)}>
      {options.map(option => (
        <button key={String(option.value)} type="button" role="radio" aria-checked={value === option.value}
          disabled={option.disabled} title={option.title} onClick={() => onChange(option.value)}
          className={cn(
            'rounded-md font-medium transition-colors disabled:opacity-40',
            size === 'xs' ? 'h-6 px-2 text-xs' : 'h-7 px-2.5 text-[13px]',
            value === option.value
              ? 'bg-nexus-bg-tertiary text-nexus-text shadow-sm ring-1 ring-inset ring-nexus-border'
              : 'text-nexus-text-muted hover:text-nexus-text',
          )}>
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** What an empty list or chart shows: an icon, what's missing, and what to do about it. */
export function EmptyState({ icon: Icon, title, description, action, className }: {
  icon: ComponentType<{ className?: string }>;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center px-6 py-10 text-center', className)}>
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg border border-nexus-border bg-nexus-bg-tertiary/60 text-nexus-text-muted">
        <Icon className="h-5 w-5" />
      </div>
      <p className="text-sm font-medium text-nexus-text">{title}</p>
      {description && <p className="mt-1 max-w-sm text-[13px] text-nexus-text-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
