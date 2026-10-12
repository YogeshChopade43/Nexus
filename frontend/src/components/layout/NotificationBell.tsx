import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlarmClock, AlertCircle, Bell, RotateCcw } from 'lucide-react';
import { Button } from '../ui/Button';
import { cn, formatRelativeTime } from '../../lib/utils';
import { activityService, type Notifications } from '../../services/activity';

const POLL_MS = 30_000;

const canNotify = () => typeof window !== 'undefined' && 'Notification' in window;

/** Failed runs, disconnected servers, resumed runs and reminders, with an unread count.
 *  New reminders open an on-screen pop-up and, when allowed, a desktop notification (while Nexus is open). */
export function NotificationBell() {
  const [data, setData] = useState<Notifications>({ unread: 0, items: [] });
  const [open, setOpen] = useState(false);
  const [permission, setPermission] = useState(() => (canNotify() ? Notification.permission : 'denied'));
  const [popups, setPopups] = useState<Notifications['items']>([]); // reminders shown on screen until dismissed
  const newestSeen = useRef<number | null>(null); // items up to this id were already there or already shown
  const containerRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  const refresh = useCallback(() => {
    activityService.getNotifications().then(next => {
      const seen = newestSeen.current;
      const fresh = seen === null ? [] : next.items.filter(i => i.type === 'reminder' && Number(i.id) > seen);
      if (fresh.length) {
        setPopups(list => [...list, ...fresh]);
        if (canNotify() && Notification.permission === 'granted') {
          fresh.forEach(i => new Notification(i.title, { body: i.description || undefined }));
        }
      }
      newestSeen.current = Math.max(seen ?? 0, ...next.items.map(i => Number(i.id) || 0));
      setData(next);
    }).catch(() => {});
  }, []);

  const allowAlerts = () => {
    void Notification.requestPermission().then(setPermission);
  };

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    window.addEventListener('focus', refresh);
    return () => { clearInterval(timer); window.removeEventListener('focus', refresh); };
  }, [refresh]);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const toggle = () => {
    const opening = !open;
    setOpen(opening);
    if (opening && data.unread > 0) {
      // Items stay highlighted while the panel is open; the count clears now.
      activityService.markNotificationsRead().then(() => setData(d => ({ ...d, unread: 0 }))).catch(() => {});
    }
    if (!opening) setData(d => ({ ...d, items: d.items.map(i => ({ ...i, unread: false })) }));
  };

  const go = (type: string) => {
    setOpen(false);
    if (type === 'reminder') return;
    navigate(type === 'server_error' ? '/servers' : type === 'document_failed' ? '/knowledge' : '/workflows');
  };

  return (
    <div ref={containerRef} className="relative" onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}>
      <Button
        variant="ghost"
        size="sm"
        onClick={toggle}
        aria-label={data.unread ? `Notifications, ${data.unread} unread` : 'Notifications'}
        aria-expanded={open}
        className="relative"
      >
        <Bell className="w-5 h-5" />
        {data.unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[1.1rem] h-[1.1rem] px-1 rounded-full bg-nexus-danger text-white text-[10px] font-semibold flex items-center justify-center">
            {data.unread > 9 ? '9+' : data.unread}
          </span>
        )}
      </Button>
      {open && (
        <div className="absolute right-0 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-xl border border-nexus-border bg-nexus-bg-secondary shadow-pop z-50" role="dialog" aria-label="Notifications">
          <div className="px-4 py-3 border-b border-nexus-border text-sm font-medium text-nexus-text">Notifications</div>
          {permission === 'default' && (
            <div className="px-4 py-2 border-b border-nexus-border text-xs text-nexus-text-secondary flex items-center gap-2">
              <span className="flex-1">Get reminders as desktop pop-ups while Nexus is open.</span>
              <Button size="sm" variant="secondary" onClick={allowAlerts}>Turn on desktop alerts</Button>
            </div>
          )}
          {data.items.length === 0 ? (
            <p className="px-4 py-6 text-sm text-nexus-text-muted text-center">Nothing needs your attention.</p>
          ) : (
            <ul className="max-h-96 overflow-y-auto divide-y divide-nexus-border">
              {data.items.map(item => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => go(item.type)}
                    className={cn('w-full text-left px-4 py-3 flex gap-2.5 hover:bg-nexus-bg-tertiary', item.unread && 'bg-nexus-accent/5')}
                  >
                    {item.type === 'reminder'
                      ? <AlarmClock className="w-4 h-4 mt-0.5 text-nexus-accent-text flex-shrink-0" />
                      : item.type === 'workflow_resumed'
                        ? <RotateCcw className="w-4 h-4 mt-0.5 text-nexus-accent-text flex-shrink-0" />
                        : <AlertCircle className="w-4 h-4 mt-0.5 text-red-400 flex-shrink-0" />}
                    <span className="min-w-0">
                      <span className="block text-sm text-nexus-text">{item.title}</span>
                      {item.description && <span className="block text-xs text-nexus-text-secondary truncate">{item.description}</span>}
                      <span className="block text-xs text-nexus-text-muted mt-0.5">{formatRelativeTime(item.timestamp)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {popups.length > 0 && (
        <div className="fixed bottom-4 right-4 left-4 sm:left-auto sm:w-80 z-[60] space-y-2">
          {popups.map(p => (
            <div key={p.id} role="alertdialog" aria-labelledby={`reminder-${p.id}`}
              className="rounded-xl border border-nexus-accent bg-nexus-bg-secondary shadow-pop p-4 flex gap-3">
              <AlarmClock className="w-5 h-5 text-nexus-accent-text flex-shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p id={`reminder-${p.id}`} className="text-sm font-semibold text-nexus-text">{p.title}</p>
                {p.description && <p className="text-sm text-nexus-text-secondary mt-0.5">{p.description}</p>}
                <Button size="sm" className="mt-3" onClick={() => setPopups(list => list.filter(x => x.id !== p.id))}>Dismiss</Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
