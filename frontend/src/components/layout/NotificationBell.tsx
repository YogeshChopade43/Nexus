import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertCircle, Bell, RotateCcw } from 'lucide-react';
import { Button } from '../ui/Button';
import { cn, formatRelativeTime } from '../../lib/utils';
import { activityService, type Notifications } from '../../services/activity';

const POLL_MS = 30_000;

/** Failed runs, disconnected servers and resumed runs, with an unread count. */
export function NotificationBell() {
  const [data, setData] = useState<Notifications>({ unread: 0, items: [] });
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  const refresh = useCallback(() => {
    activityService.getNotifications().then(setData).catch(() => {});
  }, []);

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
    navigate(type === 'server_error' ? '/servers' : '/workflows');
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
        <div className="absolute right-0 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-xl border border-nexus-border bg-nexus-bg-secondary shadow-lg z-50" role="dialog" aria-label="Notifications">
          <div className="px-4 py-3 border-b border-nexus-border text-sm font-medium text-nexus-text">Notifications</div>
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
                    {item.type === 'workflow_resumed'
                      ? <RotateCcw className="w-4 h-4 mt-0.5 text-nexus-accent flex-shrink-0" />
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
    </div>
  );
}
