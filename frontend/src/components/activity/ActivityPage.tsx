import { PageHeader, SegmentedControl } from '../ui/PageHeader';
import { useEffect, useState } from 'react';
import { Card } from '../ui/Card';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { ScrollArea } from '../ui/ScrollArea';
import {
  Activity as ActivityIcon,
  Clock,
  RefreshCw,
  AlertCircle,
  Inbox,
  Repeat1,
  GitBranch,
  Plug,
  Settings,
  MessageCircle,
  CheckCircle,
  AlarmClock,
  Undo2,
  ShieldCheck,
} from 'lucide-react';
import { useActivity } from '../../hooks/useActivity';
import { formatRelativeTime, getErrorMessage } from '../../lib/utils';
import { Modal } from '../ui/Modal';
import { activityService } from '../../services/activity';
import type { Activity, ActivityType, UndoPlan } from '../../types/activity';

type ActivityGroup = 'all' | 'messages' | 'apps' | 'workflows' | 'settings';

const typeLabels: Record<ActivityType, string> = {
  message_sent: 'Message sent',
  message_received: 'Message received',
  app_connected: 'App connected',
  app_disconnected: 'App disconnected',
  workflow_created: 'Workflow created',
  workflow_updated: 'Workflow updated',
  workflow_deleted: 'Workflow deleted',
  workflow_executed: 'Workflow executed',
  workflow_completed: 'Workflow completed',
  workflow_failed: 'Workflow failed',
  workflow_resumed: 'Workflow resumed',
  server_error: 'Server not connected',
  document_failed: 'Document failed',
  reminder: 'Reminder',
  will_armed: 'Run once set',
  will_ran: 'Ran once',
  run_once_set: 'Run once set',
  run_once_ran: 'Ran once',
  settings_changed: 'Settings changed',
  action_approved: 'Action approved',
  action_undone: 'Action undone',
};

const typeIcons: Record<ActivityType, typeof ActivityIcon> = {
  message_sent: MessageCircle,
  message_received: MessageCircle,
  app_connected: Plug,
  app_disconnected: Plug,
  workflow_created: GitBranch,
  workflow_updated: GitBranch,
  workflow_deleted: GitBranch,
  workflow_executed: CheckCircle,
  workflow_completed: CheckCircle,
  workflow_failed: AlertCircle,
  workflow_resumed: CheckCircle,
  server_error: AlertCircle,
  document_failed: AlertCircle,
  reminder: AlarmClock,
  will_armed: Repeat1,
  will_ran: Repeat1,
  run_once_set: Repeat1,
  run_once_ran: Repeat1,
  settings_changed: Settings,
  action_approved: ShieldCheck,
  action_undone: Undo2,
};

function activityGroup(type: ActivityType): ActivityGroup {
  if (type === 'message_sent' || type === 'message_received') return 'messages';
  if (type === 'app_connected' || type === 'app_disconnected' || type === 'server_error' || type === 'action_approved' || type === 'action_undone') return 'apps';
  if (
    type === 'workflow_created' ||
    type === 'workflow_updated' ||
    type === 'workflow_deleted' ||
    type === 'workflow_executed' ||
    type === 'workflow_completed' ||
    type === 'workflow_failed' ||
    type === 'workflow_resumed' ||
    type === 'reminder' ||
    type === 'will_armed' ||
    type === 'will_ran' ||
    type === 'run_once_set' ||
    type === 'run_once_ran'
  ) return 'workflows';
  return 'settings';
}

/** Undo for an action approved in chat: the AI proposes the reverse call, the user confirms it. */
function UndoAction({ activity }: { activity: Activity }) {
  const [undone, setUndone] = useState(Boolean(activity.metadata?.undone_at));
  const [open, setOpen] = useState(false);
  const [plan, setPlan] = useState<UndoPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (undone) return <Badge variant="success" size="sm">Undone</Badge>;

  const start = async () => {
    setOpen(true);
    setPlan(null);
    setError(null);
    setBusy(true);
    try {
      setPlan(await activityService.planUndo(activity.id));
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!plan) return;
    setBusy(true);
    setError(null);
    try {
      await activityService.runUndo(activity.id, plan);
      setUndone(true);
      setOpen(false);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Button variant="secondary" size="sm" onClick={() => void start()} className="gap-1.5">
        <Undo2 className="w-3.5 h-3.5" aria-hidden /> Undo
      </Button>
      <Modal open={open} onClose={() => setOpen(false)} title="Undo this action?" size="md">
        <div className="space-y-3">
          {busy && !plan && <p className="text-sm text-nexus-text-muted">Working out how to undo it…</p>}
          {plan && (
            <>
              <p className="text-sm text-nexus-text">{plan.explanation}</p>
              <pre className="p-2 bg-nexus-bg text-nexus-text-secondary text-xs font-mono rounded overflow-x-auto max-w-full">
                {`${plan.tool}
${JSON.stringify(plan.arguments, null, 2)}`}
              </pre>
            </>
          )}
          {error && <p className="text-sm text-nexus-danger">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>Cancel</Button>
            {plan && (
              <Button variant="primary" size="sm" onClick={() => void confirm()} disabled={busy}>
                {busy ? 'Undoing…' : 'Undo it'}
              </Button>
            )}
          </div>
        </div>
      </Modal>
    </>
  );
}

export function ActivityCard({ activity }: { activity: Activity }) {
  const Icon = typeIcons[activity.type] ?? ActivityIcon;
  const isError = activity.type === 'app_disconnected' || activity.type === 'workflow_failed';

  return (
    <div className="flex gap-3 p-4 bg-nexus-bg-tertiary/40 border-nexus-border border rounded-lg">
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${isError ? 'bg-nexus-danger/10 text-nexus-danger' : 'bg-nexus-accent-dim text-nexus-accent-text'}`}>
        <Icon className="w-5 h-5" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-nexus-text">{activity.title}</span>
          <Badge variant={isError ? 'danger' : 'default'} size="sm">{typeLabels[activity.type]}</Badge>
          {activity.type === 'action_approved' && <span className="ml-auto"><UndoAction activity={activity} /></span>}
        </div>
        <p className="text-sm text-nexus-text-secondary mt-1 break-words">{activity.description}</p>
        {Object.keys(activity.metadata ?? {}).length > 0 && (
          <details className="mt-2 group">
            <summary className="text-xs text-nexus-text-muted cursor-pointer">View details</summary>
            <pre className="mt-2 p-2 bg-nexus-bg text-nexus-text-secondary text-xs font-mono rounded overflow-x-auto max-w-full">
              {JSON.stringify(activity.metadata, null, 2)}
            </pre>
          </details>
        )}
        <time className="block text-xs text-nexus-text-muted mt-2">{formatRelativeTime(activity.timestamp)}</time>
      </div>
    </div>
  );
}

export function ActivityPage() {
  const { activities, loading, error, hasMore, fetchActivities, fetchRecent } = useActivity();
  const [filter, setFilter] = useState<ActivityGroup>('all');

  const loadActivities = () => fetchActivities({ limit: 50 });
  const loadMore = () => fetchActivities({ limit: 50, offset: activities.length }, true);

  useEffect(() => {
    void loadActivities();
  }, []);

  const visibleActivities = filter === 'all'
    ? activities
    : activities.filter(activity => activityGroup(activity.type) === filter);

  return (
    <div className="space-y-6">
      <PageHeader title="Activity" description="Everything that happened in your workspace: chats, approvals, workflow runs and app connections."
        actions={
          <Button variant="secondary" size="sm" onClick={() => void fetchRecent(50)} disabled={loading}>
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        } />

      {error && (
        <Card className="p-4 border-nexus-danger/30 bg-red-500/5">
          <div className="flex items-center gap-2 text-nexus-danger">
            <AlertCircle className="w-5 h-5" />
            <span>{error.message || 'Unable to load activity'}</span>
          </div>
        </Card>
      )}

      <Card padding="none">
        <div className="p-4 border-b-nexus-border border-b flex items-center justify-between gap-3 flex-wrap">
          <SegmentedControl label="Show" value={filter} onChange={setFilter} options={[
            { value: 'all', label: 'All' }, { value: 'messages', label: 'Messages' }, { value: 'apps', label: 'Apps' },
            { value: 'workflows', label: 'Workflows' }, { value: 'settings', label: 'Settings' },
          ]} />
          <div className="text-xs text-nexus-text-muted">{activities.length} event(s)</div>
        </div>

        {loading && activities.length === 0 ? (
          <div className="h-[400px] flex items-center justify-center">
            <RefreshCw className="w-8 h-8 animate-spin text-nexus-accent-text" />
          </div>
        ) : visibleActivities.length === 0 ? (
          <div className="h-[400px] flex flex-col items-center justify-center text-center text-nexus-text-muted">
            <Inbox className="w-12 h-12 text-nexus-text-muted/50 mb-4" />
            <h3 className="text-lg font-medium text-nexus-text mb-1">No activity found</h3>
            <p className="text-sm">Events will appear here as you use Nexus.</p>
          </div>
        ) : (
          <ScrollArea className="max-h-[620px] p-4 space-y-3">
            {visibleActivities.map(activity => <ActivityCard key={activity.id} activity={activity} />)}
            {hasMore && (
              <Button variant="secondary" className="w-full gap-1.5" onClick={() => void loadMore()} disabled={loading}>
                <Clock className="w-4 h-4" />
                Load older activity
              </Button>
            )}
          </ScrollArea>
        )}
      </Card>
    </div>
  );
}
