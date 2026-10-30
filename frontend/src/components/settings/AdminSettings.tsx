import { useEffect, useState } from 'react';
import { CheckCircle2, AlertTriangle } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/Card';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { fieldClass } from '../ui/Input';
import { useAuth } from '../../hooks/useAuth';
import { adminService, type AdminUser, type DeploymentCheck } from '../../services/admin';
import { cn, formatRelativeTime, getErrorMessage } from '../../lib/utils';

const number = new Intl.NumberFormat();
const megabytes = (bytes: number) => `${(bytes / 1048576).toFixed(1)} MB`;

/** Settings › Admin: is this Nexus ready to publish, who uses it, and the rules for everyone. */
export function AdminSettings() {
  const { user: me } = useAuth();
  const [checks, setChecks] = useState<DeploymentCheck[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [signups, setSignups] = useState('');
  const [storage, setStorage] = useState('1024');
  const [privacyUrl, setPrivacyUrl] = useState('');
  const [termsUrl, setTermsUrl] = useState('');
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    adminService.deployment().then(setChecks, () => {});
    adminService.users().then(setUsers, () => {});
    adminService.instance().then(i => {
      setSignups(i.signups ?? '');
      setStorage(String(i.storageLimitMb));
      setPrivacyUrl(i.privacyUrl ?? '');
      setTermsUrl(i.termsUrl ?? '');
    }, () => {});
  }, []);

  const change = async (user: AdminUser, changes: { disabled?: boolean; isAdmin?: boolean }) => {
    try {
      const updated = await adminService.changeUser(user.id, changes);
      setUsers(list => list.map(u => (u.id === user.id ? updated : u)));
    } catch (err) {
      setNote({ ok: false, text: getErrorMessage(err) });
    }
  };

  const save = async () => {
    try {
      await adminService.changeInstance({ signups: signups === '' ? null : signups as 'open' | 'closed',
        storageLimitMb: Math.max(0, Number(storage) || 0), privacyUrl: privacyUrl.trim(), termsUrl: termsUrl.trim() });
      setNote({ ok: true, text: 'Saved.' });
      adminService.deployment().then(setChecks, () => {});
    } catch (err) {
      setNote({ ok: false, text: getErrorMessage(err) });
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Ready to publish?</CardTitle>
          <CardDescription>What a Nexus others reach over the internet should have. Set these in the server&apos;s environment.</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="divide-y divide-nexus-border rounded-lg border border-nexus-border">
            {checks.map(check => (
              <li key={check.id} className="flex items-start gap-3 px-3 py-2.5">
                {check.ok
                  ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-nexus-success" aria-hidden />
                  : <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-nexus-warning" aria-hidden />}
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] font-medium text-nexus-text">{check.title}</p>
                  <p className="text-xs text-nexus-text-muted">{check.detail}</p>
                </div>
                <Badge size="sm" variant={check.ok ? 'success' : 'warning'}>{check.ok ? 'Ready' : 'Needs attention'}</Badge>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Rules for everyone</CardTitle>
          <CardDescription>
            Admins have no storage limit; 0 MB means no limit for anyone. Your privacy policy and terms (pages you host
            anywhere) are linked on the sign-in page.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-3">
            <label className="block space-y-1">
              <span className="block text-[13px] font-medium text-nexus-text">Sign-ups</span>
              <select aria-label="Sign-ups" className={fieldClass} value={signups} onChange={e => setSignups(e.target.value)}>
                <option value="">Server default: open, unless NEXUS_SIGNUPS=closed</option>
                <option value="open">Open: anyone can create an account</option>
                <option value="closed">Closed: existing accounts only</option>
              </select>
            </label>
            <label className="block space-y-1">
              <span className="block text-[13px] font-medium text-nexus-text">Storage per person (MB)</span>
              <input aria-label="Storage per person (MB)" type="number" min={0} className={cn(fieldClass, 'w-32')}
                value={storage} onChange={e => setStorage(e.target.value)} />
            </label>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="block space-y-1">
              <span className="block text-[13px] font-medium text-nexus-text">Privacy policy link</span>
              <input aria-label="Privacy policy link" type="url" placeholder="https://example.com/privacy" className={fieldClass}
                value={privacyUrl} onChange={e => setPrivacyUrl(e.target.value)} />
            </label>
            <label className="block space-y-1">
              <span className="block text-[13px] font-medium text-nexus-text">Terms link</span>
              <input aria-label="Terms link" type="url" placeholder="https://example.com/terms" className={fieldClass}
                value={termsUrl} onChange={e => setTermsUrl(e.target.value)} />
            </label>
          </div>
          <div className="mt-3"><Button size="sm" onClick={() => void save()}>Save</Button></div>
          {note && <p role={note.ok ? 'status' : 'alert'} className={cn('mt-2 text-xs', note.ok ? 'text-nexus-success' : 'text-nexus-danger')}>{note.text}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Accounts</CardTitle>
          <CardDescription>Disabling someone signs them out everywhere; their data stays until you enable them again.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <thead className="text-xs text-nexus-text-muted">
              <tr><th className="py-2 pr-3 font-medium">Account</th><th className="py-2 pr-3 font-medium">Joined</th>
                <th className="py-2 pr-3 text-right font-medium">Tokens (30 days)</th><th className="py-2 pr-3 text-right font-medium">Storage</th>
                <th className="py-2 font-medium"><span className="sr-only">Actions</span></th></tr>
            </thead>
            <tbody className="divide-y divide-nexus-border">
              {users.map(user => (
                <tr key={user.id} className={cn(user.disabled && 'opacity-60')}>
                  <td className="py-2.5 pr-3">
                    <p className="text-nexus-text">{user.email}</p>
                    <p className="flex flex-wrap gap-1 pt-0.5 text-xs text-nexus-text-muted">
                      {user.name}
                      {user.isAdmin && <Badge size="sm" variant="accent">Admin</Badge>}
                      {user.disabled && <Badge size="sm" variant="danger">Disabled</Badge>}
                    </p>
                  </td>
                  <td className="py-2.5 pr-3 text-nexus-text-muted">{formatRelativeTime(user.createdAt)}</td>
                  <td className="py-2.5 pr-3 text-right tabular-nums">{number.format(user.tokens30d)}</td>
                  <td className="py-2.5 pr-3 text-right tabular-nums">{megabytes(user.storageBytes)}</td>
                  <td className="py-2.5 text-right">
                    {user.id !== me?.id && (
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="sm" aria-label={`${user.isAdmin ? 'Remove admin from' : 'Make admin'} ${user.email}`}
                          onClick={() => void change(user, { isAdmin: !user.isAdmin })}>
                          {user.isAdmin ? 'Remove admin' : 'Make admin'}
                        </Button>
                        <Button variant="ghost" size="sm" className={cn(!user.disabled && 'text-nexus-danger')}
                          aria-label={`${user.disabled ? 'Enable' : 'Disable'} ${user.email}`}
                          onClick={() => void change(user, { disabled: !user.disabled })}>
                          {user.disabled ? 'Enable' : 'Disable'}
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
