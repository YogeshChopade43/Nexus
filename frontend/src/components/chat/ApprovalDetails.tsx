import { Fragment } from 'react';
import { humanize } from '../workflow/toolInfo';

/** A tool argument as a person reads it: text as is, Yes/No, lists with commas, small objects as "Key: value". */
function formatValue(value: unknown, depth = 0): string {
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.map(v => formatValue(v, depth + 1)).join(', ');
  if (value && typeof value === 'object') {
    if (depth > 1) return JSON.stringify(value);  // deeply nested: rare, keep it compact
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${humanize(k)}: ${formatValue(v, depth + 1)}`).join('; ');
  }
  return '';
}

/** The details of an action waiting for approval, as labelled fields instead of JSON. */
export function ApprovalDetails({ arguments: args }: { arguments: Record<string, unknown> | undefined }) {
  const entries = Object.entries(args ?? {}).filter(([, v]) => v !== null && v !== undefined && v !== '');
  if (entries.length === 0) return null;
  return (
    <dl className="grid gap-x-4 gap-y-1.5 sm:grid-cols-[auto_1fr] rounded-lg bg-nexus-bg-tertiary/50 border border-nexus-border p-3 max-h-60 overflow-y-auto">
      {entries.map(([key, value]) => (
        <Fragment key={key}>
          <dt className="text-xs font-medium text-nexus-text-muted sm:pt-0.5">{humanize(key)}</dt>
          <dd className="text-sm text-nexus-text whitespace-pre-wrap break-words">{formatValue(value)}</dd>
        </Fragment>
      ))}
    </dl>
  );
}
