import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, CheckCircle2, Clock, Smartphone } from 'lucide-react';
import { api } from '../../services/api';
import { cn, formatRelativeTime } from '../../lib/utils';

export interface Status {
  scheduler: { running: boolean; jobs: number };
  apps: Array<{ name: string; kind: string; status: string; error: string | null }>;
  last_failure: { workflow_id: number; name: string; started_at: string; error: string | null } | null;
  telegram_linked: boolean;
}

/** "Is everything working?": the scheduler, each app, the last failed run, and whether alerts reach the phone. */
export function SystemStatus() {
  const [status, setStatus] = useState<Status | null>(null);
  useEffect(() => { api.get<Status>('/api/dashboard/status').then(setStatus).catch(() => setStatus(null)); }, []);
  if (!status) return null;

  const broken = status.apps.filter(a => a.status !== 'connected' && a.status !== 'stopped' && a.status !== 'connecting');
  const issues = (status.scheduler.running ? 0 : 1) + broken.length + (status.last_failure ? 1 : 0);
  const ok = issues === 0;

  return (
    <section aria-label="System status" className={cn('rounded-xl border p-4 shadow-surface',
      ok ? 'border-nexus-border bg-nexus-bg-secondary' : 'border-nexus-warning/40 bg-nexus-warning/5')}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="flex items-center gap-2 text-[13px] font-semibold text-nexus-text">
          {ok ? <CheckCircle2 className="h-4 w-4 text-nexus-success" aria-hidden /> : <AlertTriangle className="h-4 w-4 text-nexus-warning" aria-hidden />}
          {ok ? 'Everything is working' : `${issues} ${issues === 1 ? 'thing needs' : 'things need'} attention`}
        </p>
        <span className="flex items-center gap-1.5 text-xs text-nexus-text-muted">
          <Clock className="h-3.5 w-3.5" aria-hidden />
          {status.scheduler.running ? `Scheduler running · ${status.scheduler.jobs} scheduled` : 'Scheduler stopped: scheduled workflows won\'t run'}
        </span>
        <span className="flex items-center gap-1.5 text-xs text-nexus-text-muted">
          <Smartphone className="h-3.5 w-3.5" aria-hidden />
          {status.telegram_linked ? 'Reminders and failures reach your phone'
            : <Link to="/servers">Link Telegram to get reminders on your phone</Link>}
        </span>
        <span className="ml-auto text-xs text-nexus-text-muted">{status.apps.length} app(s) connected</span>
      </div>
      {!ok && (
        <ul className="mt-3 min-w-0 space-y-1.5 text-[13px] [overflow-wrap:anywhere]">
          {broken.map(app => (
            <li key={app.name} className="flex flex-wrap items-baseline gap-1.5 text-nexus-text-secondary">
              <span className="font-medium text-nexus-text">{app.name}</span>
              <span>{app.status === 'needs_auth' ? 'needs you to sign in or link it' : 'isn\'t connected'}{app.error ? `: ${app.error}` : ''}</span>
              <Link to="/servers" className="text-xs">Fix in Marketplace</Link>
            </li>
          ))}
          {status.last_failure && (
            <li className="flex flex-wrap items-baseline gap-1.5 text-nexus-text-secondary">
              <span>Last failed run:</span>
              <Link to={`/workflows?open=${status.last_failure.workflow_id}`} className="font-medium">{status.last_failure.name}</Link>
              <span className="text-xs text-nexus-text-muted">{formatRelativeTime(status.last_failure.started_at)}</span>
              {status.last_failure.error && <span className="text-xs">· {status.last_failure.error}</span>}
            </li>
          )}
        </ul>
      )}
    </section>
  );
}
