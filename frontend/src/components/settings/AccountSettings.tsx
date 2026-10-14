import { useEffect, useState, type FormEvent } from 'react';
import { Download, LogOut, Monitor, Trash2 } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/Card';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { fieldClass } from '../ui/Input';
import { useAuth } from '../../hooks/useAuth';
import { authService, type AuthSession } from '../../services/auth';
import { cn, formatRelativeTime, getErrorMessage } from '../../lib/utils';

function Field({ label, ...input }: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block space-y-1">
      <span className="block text-[13px] font-medium text-nexus-text">{label}</span>
      <input aria-label={label} className={fieldClass} {...input} />
    </label>
  );
}

function Note({ ok, text }: { ok: boolean; text: string }) {
  return <p role={ok ? 'status' : 'alert'} className={cn('text-xs', ok ? 'text-nexus-success' : 'text-nexus-danger')}>{text}</p>;
}

/** Settings › Account: who you are, your password, where you're signed in, your data. */
export function AccountSettings() {
  const { user, signedIn, signedOut } = useAuth();
  const [name, setName] = useState(user?.name ?? '');
  const [nameNote, setNameNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [passwordNote, setPasswordNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [sessions, setSessions] = useState<AuthSession[]>([]);
  const [deleting, setDeleting] = useState(false);
  const [confirm, setConfirm] = useState('');
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const loadSessions = () => { authService.sessions().then(setSessions, () => {}); };
  useEffect(loadSessions, []);

  if (!user) return null;

  const saveName = async (e: FormEvent) => {
    e.preventDefault();
    try {
      signedIn(await authService.rename(name.trim()));
      setNameNote({ ok: true, text: 'Saved.' });
    } catch (err) {
      setNameNote({ ok: false, text: getErrorMessage(err) });
    }
  };

  const changePassword = async (e: FormEvent) => {
    e.preventDefault();
    if (next.length < 10) {
      setPasswordNote({ ok: false, text: 'At least 10 characters for your new password, please.' });
      return;
    }
    try {
      await authService.changePassword(current, next);
      setCurrent('');
      setNext('');
      setPasswordNote({ ok: true, text: 'Password changed. Your other devices were signed out.' });
      loadSessions();
    } catch (err) {
      setPasswordNote({ ok: false, text: getErrorMessage(err) });
    }
  };

  const deleteAccount = async () => {
    setDeleteError(null);
    try {
      await authService.deleteAccount(confirm);
      signedOut();
    } catch (err) {
      setDeleteError(getErrorMessage(err));
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Your account {user.isAdmin && <Badge size="sm" variant="accent">Admin</Badge>}
          </CardTitle>
          <CardDescription>
            {user.email}{user.google ? ' · signs in with Google' : ''}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={(e) => void saveName(e)} className="flex flex-wrap items-end gap-2">
            <div className="min-w-[14rem] flex-1"><Field label="Name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} /></div>
            <Button type="submit" size="sm" variant="secondary" disabled={name.trim() === user.name}>Save name</Button>
          </form>
          {nameNote && <div className="mt-2"><Note {...nameNote} /></div>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{user.hasPassword === false ? 'Add a password' : 'Password'}</CardTitle>
          <CardDescription>Changing it signs you out on your other devices.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={(e) => void changePassword(e)} className="grid gap-3 sm:grid-cols-2">
            {user.hasPassword !== false && (
              <Field label="Current password" type="password" value={current} autoComplete="current-password" onChange={(e) => setCurrent(e.target.value)} />
            )}
            <Field label="New password" type="password" value={next} autoComplete="new-password" onChange={(e) => setNext(e.target.value)} />
            <div className="sm:col-span-2 flex items-center gap-3">
              <Button type="submit" size="sm" disabled={!next}>Change password</Button>
              {passwordNote && <Note {...passwordNote} />}
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Where you&apos;re signed in</CardTitle>
          <CardDescription>Sign out anything you don&apos;t recognise.</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="divide-y divide-nexus-border rounded-lg border border-nexus-border">
            {sessions.map(session => (
              <li key={session.id} className="flex items-center gap-3 px-3 py-2.5">
                <Monitor className="h-4 w-4 shrink-0 text-nexus-text-muted" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] text-nexus-text">{session.userAgent || 'Unknown device'}</p>
                  <p className="text-xs text-nexus-text-muted">Signed in {formatRelativeTime(session.createdAt)}</p>
                </div>
                {session.current ? <Badge size="sm" variant="success">This device</Badge> : (
                  <Button variant="ghost" size="sm" aria-label={`Sign out ${session.userAgent || 'that device'}`}
                    onClick={() => { authService.endSession(session.id).then(loadSessions, () => {}); }}>
                    <LogOut className="h-3.5 w-3.5" /> Sign out
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Your data</CardTitle>
          <CardDescription>Everything in your account belongs to you: take a copy, or delete it all.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <a href={authService.exportUrl()} download
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-nexus-border px-3 text-[13px] font-medium text-nexus-text hover:bg-nexus-bg-tertiary hover:no-underline">
            <Download className="h-3.5 w-3.5" aria-hidden /> Export my data (JSON)
          </a>
          {!deleting ? (
            <div><Button variant="ghost" size="sm" className="text-nexus-danger" onClick={() => setDeleting(true)}>
              <Trash2 className="h-3.5 w-3.5" /> Delete my account…
            </Button></div>
          ) : (
            <div className="space-y-3 rounded-lg border border-nexus-danger/40 bg-nexus-danger/5 p-4">
              <p className="text-[13px] text-nexus-text">
                This deletes your account and everything in it: chats, workflows, documents, connected apps, keys and
                files. It can&apos;t be undone.
              </p>
              {user.hasPassword === false
                ? <Field label="Your email" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
                : <Field label="Your password" type="password" value={confirm} autoComplete="current-password" onChange={(e) => setConfirm(e.target.value)} />}
              {deleteError && <Note ok={false} text={deleteError} />}
              <div className="flex gap-2">
                <Button size="sm" variant="danger" disabled={!confirm} onClick={() => void deleteAccount()}>Delete everything</Button>
                <Button size="sm" variant="ghost" onClick={() => { setDeleting(false); setConfirm(''); }}>Cancel</Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
