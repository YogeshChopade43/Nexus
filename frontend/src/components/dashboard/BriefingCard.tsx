import { useEffect, useState } from 'react';
import { Newspaper, Send } from 'lucide-react';
import { api } from '../../services/api';
import { getErrorMessage } from '../../lib/utils';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { Modal } from '../ui/Modal';
import { fieldClass } from '../ui/Input';
import { Markdown } from '../chat/Markdown';

interface Briefing {
  enabled: boolean;
  workflow_id: number | null;
  time: string;
  weekdays_only: boolean;
  sections: string[];
  notes: string;
  next_run_at: string | null;
}

const SECTIONS: Array<[string, string]> = [
  ['calendar', "Today's meetings and events"],
  ['email', 'Important unread email'],
  ['apps', 'What needs me in my apps (issues, PRs, tasks)'],
  ['feeds', 'New posts in my feeds'],
];

/** A morning summary from calendar, email, apps and feeds, sent to the bell and the phone. */
export function BriefingCard() {
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [draft, setDraft] = useState<Briefing | null>(null);
  const [busy, setBusy] = useState<'save' | 'send' | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.get<Briefing>('/api/briefing').then(setBriefing).catch(() => {}); }, []);
  if (!briefing) return null;

  const open = () => { setDraft({ ...briefing, enabled: true }); setPreview(null); setError(null); };
  const save = async () => {
    if (!draft) return;
    setBusy('save');
    setError(null);
    try {
      const { enabled, time, weekdays_only, sections, notes } = draft;
      setBriefing(await api.put<Briefing>('/api/briefing', { enabled, time, weekdays_only, sections, notes }));
      setDraft(null);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };
  const sendNow = async () => {
    if (!draft) return;
    setBusy('send');
    setError(null);
    try {
      const { time, weekdays_only, sections, notes } = draft;  // use what's on screen, without switching it on
      await api.put<Briefing>('/api/briefing', { enabled: briefing.enabled, time, weekdays_only, sections, notes });
      setPreview((await api.post<{ text: string }>('/api/briefing/send-now')).text);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(null);
    }
  };
  const toggle = (section: string) => draft && setDraft({
    ...draft, sections: draft.sections.includes(section) ? draft.sections.filter(s => s !== section) : [...draft.sections, section],
  });

  return (
    <section aria-label="Daily briefing" className="flex flex-wrap items-center gap-3 rounded-xl border border-nexus-border bg-nexus-bg-secondary p-4 shadow-surface">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-nexus-border bg-nexus-bg-tertiary text-nexus-text-secondary">
        <Newspaper className="h-4 w-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2 text-[13px] font-semibold text-nexus-text">
          Daily briefing {briefing.enabled ? <Badge size="sm" variant="success">On</Badge> : <Badge size="sm">Off</Badge>}
        </p>
        <p className="text-xs text-nexus-text-muted">
          {briefing.enabled && briefing.next_run_at
            ? `Next: ${new Date(briefing.next_run_at).toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' })} · to your bell and phone`
            : 'A morning summary of your meetings, important email, app updates and feeds, sent to your phone.'}
        </p>
      </div>
      <Button variant={briefing.enabled ? 'secondary' : 'primary'} size="sm" onClick={open}>{briefing.enabled ? 'Edit' : 'Set up'}</Button>

      {draft && (
        <Modal open onClose={() => setDraft(null)} title="Daily briefing" size="lg"
          description="Nexus reads your apps (read-only) and sends you a short summary. Sections with nothing in them are left out.">
          <div className="space-y-4">
            <label className="flex items-center gap-2 text-[13px] text-nexus-text">
              <input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />
              Send it every morning
            </label>
            <div className="flex flex-wrap items-end gap-4">
              <div className="space-y-1">
                <label htmlFor="briefing-time" className="block text-[13px] font-medium text-nexus-text">Time</label>
                <input id="briefing-time" type="time" value={draft.time} onChange={(e) => setDraft({ ...draft, time: e.target.value })}
                  className={`${fieldClass} w-32`} />
              </div>
              <label className="flex items-center gap-2 pb-2 text-[13px] text-nexus-text-secondary">
                <input type="checkbox" checked={draft.weekdays_only} onChange={(e) => setDraft({ ...draft, weekdays_only: e.target.checked })} />
                Weekdays only
              </label>
            </div>
            <fieldset className="space-y-1.5">
              <legend className="mb-1 text-[13px] font-medium text-nexus-text">Include</legend>
              {SECTIONS.map(([id, label]) => (
                <label key={id} className="flex items-center gap-2 text-[13px] text-nexus-text-secondary">
                  <input type="checkbox" checked={draft.sections.includes(id)} onChange={() => toggle(id)} /> {label}
                </label>
              ))}
            </fieldset>
            <div className="space-y-1">
              <label htmlFor="briefing-notes" className="block text-[13px] font-medium text-nexus-text">Anything else? (optional)</label>
              <textarea id="briefing-notes" rows={2} maxLength={500} value={draft.notes} placeholder="e.g. Skip newsletters. Mention the weather in Pune."
                onChange={(e) => setDraft({ ...draft, notes: e.target.value })} className={fieldClass} />
            </div>
            {error && <p role="alert" className="text-[13px] text-nexus-danger">{error}</p>}
            {preview !== null && (
              <div className="max-h-72 overflow-y-auto rounded-lg border border-nexus-border bg-nexus-bg-tertiary/40 p-3">
                <p className="mb-2 text-xs text-nexus-text-muted">Sent just now:</p>
                <Markdown text={preview} />
              </div>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="secondary" size="sm" loading={busy === 'send'} disabled={!!busy || draft.sections.length === 0} onClick={() => void sendNow()}>
                <Send className="h-3.5 w-3.5" /> Send one now
              </Button>
              <Button size="sm" loading={busy === 'save'} disabled={!!busy || draft.sections.length === 0} onClick={() => void save()}>Save</Button>
            </div>
          </div>
        </Modal>
      )}
    </section>
  );
}
