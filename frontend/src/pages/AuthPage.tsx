import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { CheckCircle2, MailCheck } from 'lucide-react';
import { Logo } from '../components/layout/Sidebar';
import { Button } from '../components/ui/Button';
import { fieldClass } from '../components/ui/Input';
import { useAuth } from '../hooks/useAuth';
import { authService } from '../services/auth';
import { getErrorMessage } from '../lib/utils';

const MIN_PASSWORD = 10;

/** The centred card every sign-in page sits in. */
function AuthCard({ title, subtitle, children, footer }: { title: string; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-nexus-bg px-4 py-10">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center gap-3 text-center">
          <Logo className="h-10 w-10" />
          <h1 className="text-xl font-semibold text-nexus-text">{title}</h1>
          {subtitle && <p className="text-[13px] text-nexus-text-secondary">{subtitle}</p>}
        </div>
        <div className="space-y-4 rounded-xl border border-nexus-border bg-nexus-bg-secondary p-6 shadow-surface">{children}</div>
        {footer && <p className="text-center text-[13px] text-nexus-text-secondary">{footer}</p>}
      </div>
    </div>
  );
}

function Field({ label, hint, ...input }: { label: string; hint?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block space-y-1">
      <span className="block text-[13px] font-medium text-nexus-text">{label}</span>
      <input aria-label={label} className={fieldClass} {...input} />
      {hint && <span className="block text-xs text-nexus-text-muted">{hint}</span>}
    </label>
  );
}

function GoogleButton() {
  return (
    <a href={authService.googleStartUrl()}
      className="flex h-9 w-full items-center justify-center gap-2 rounded-md border border-nexus-border bg-nexus-bg text-[13px] font-medium text-nexus-text transition-colors hover:bg-nexus-bg-tertiary hover:no-underline">
      <span aria-hidden className="bg-[conic-gradient(from_-45deg,#ea4335_0_25%,#4285f4_0_50%,#34a853_0_75%,#fbbc05_0)] bg-clip-text text-base font-bold text-transparent">G</span>
      Continue with Google
    </a>
  );
}

/** Sign in, or create an account (on a fresh install: the owner's). */
export function AuthPage({ mode }: { mode: 'login' | 'signup' }) {
  const { login, signup, status } = useAuth();
  const [params] = useSearchParams();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(params.get('error'));  // e.g. back from Google
  const [busy, setBusy] = useState(false);
  const firstAccount = status?.hasUsers === false;
  const signingUp = mode === 'signup';

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (signingUp && password.length < MIN_PASSWORD) {
      setError(`At least ${MIN_PASSWORD} characters for your password, please.`);
      return;
    }
    setBusy(true);
    try {
      if (signingUp) await signup(name.trim(), email.trim(), password);
      else await login(email.trim(), password);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthCard title={signingUp ? 'Create your Nexus account' : 'Sign in to Nexus'}
      subtitle={signingUp && firstAccount ? 'You’re the first here, so this account owns this Nexus.' : undefined}
      footer={signingUp
        ? (status?.hasUsers ? <>Have an account? <Link to="/login" className="text-nexus-accent-text">Sign in</Link></> : null)
        : status?.signupsOpen ? <>New here? <Link to="/signup" className="text-nexus-accent-text">Create an account</Link></> : null}>
      {status?.google && (
        <>
          <GoogleButton />
          <div className="flex items-center gap-3 text-[11px] uppercase tracking-wider text-nexus-text-muted">
            <span className="h-px flex-1 bg-nexus-border" />or<span className="h-px flex-1 bg-nexus-border" />
          </div>
        </>
      )}
      <form onSubmit={(e) => void submit(e)} className="space-y-4">
        {signingUp && <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" maxLength={80} />}
        <Field label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required />
        <Field label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
          autoComplete={signingUp ? 'new-password' : 'current-password'} hint={signingUp ? `At least ${MIN_PASSWORD} characters.` : undefined} />
        {!signingUp && status?.email && (
          <div className="-mt-2 text-right"><Link to="/forgot-password" className="text-xs text-nexus-accent-text">Forgot password?</Link></div>
        )}
        {error && <p role="alert" className="text-[13px] text-nexus-danger">{error}</p>}
        <Button type="submit" className="w-full" loading={busy}>{signingUp ? 'Create account' : 'Sign in'}</Button>
      </form>
    </AuthCard>
  );
}

function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    await authService.forgotPassword(email.trim()).catch(() => {});  // the same answer either way
    setSent(email.trim());
    setBusy(false);
  };
  return (
    <AuthCard title="Reset your password" footer={<Link to="/login" className="text-nexus-accent-text">Back to sign in</Link>}>
      {sent ? (
        <p role="status" className="flex items-start gap-2 text-[13px] text-nexus-text-secondary">
          <MailCheck className="mt-0.5 h-4 w-4 shrink-0 text-nexus-accent-text" aria-hidden />
          If there&apos;s an account for {sent}, we&apos;ve sent it a link to choose a new password. It works for an hour.
        </p>
      ) : (
        <form onSubmit={(e) => void submit(e)} className="space-y-4">
          <Field label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required />
          <Button type="submit" className="w-full" loading={busy}>Send reset link</Button>
        </form>
      )}
    </AuthCard>
  );
}

function ResetPassword() {
  const { signedIn } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < MIN_PASSWORD) {
      setError(`At least ${MIN_PASSWORD} characters for your password, please.`);
      return;
    }
    setBusy(true);
    try {
      signedIn(await authService.resetPassword(params.get('token') ?? '', password));
      navigate('/', { replace: true });
    } catch (err) {
      setError(getErrorMessage(err));
      setBusy(false);
    }
  };
  return (
    <AuthCard title="Choose a new password" subtitle="This signs you out on your other devices."
      footer={<Link to="/forgot-password" className="text-nexus-accent-text">Need a new link?</Link>}>
      <form onSubmit={(e) => void submit(e)} className="space-y-4">
        <Field label="New password" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
          autoComplete="new-password" required hint={`At least ${MIN_PASSWORD} characters.`} />
        {error && <p role="alert" className="text-[13px] text-nexus-danger">{error}</p>}
        <Button type="submit" className="w-full" loading={busy}>Set new password</Button>
      </form>
    </AuthCard>
  );
}

/** Opened from the email: confirms the address, then on to the app (or to signing in). */
function VerifyEmail() {
  const { signedIn, user } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const tried = useRef(false);
  useEffect(() => {
    if (tried.current) return;  // a link works once: don't send it twice
    tried.current = true;
    authService.verifyEmail(params.get('token') ?? '')
      .then((verified) => {
        if (user) signedIn({ ...user, ...verified });
        navigate(user ? '/' : '/login', { replace: true });
      })
      .catch(err => setError(getErrorMessage(err)));
  }, [params, navigate, signedIn, user]);
  return (
    <AuthCard title="Confirming your email…" footer={<Link to="/" className="text-nexus-accent-text">Go to Nexus</Link>}>
      {error ? <p role="alert" className="text-[13px] text-nexus-danger">{error}</p>
        : <p className="text-[13px] text-nexus-text-muted">One moment.</p>}
    </AuthCard>
  );
}

/** Signed in, but the email still has to be confirmed before using Nexus. */
function CheckEmail() {
  const { user, logout } = useAuth();
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <AuthCard title="Check your email" subtitle={<>We sent a link to <b className="text-nexus-text">{user?.email}</b>. Open it to start using Nexus.</>}
      footer={<button type="button" onClick={() => void logout()} className="text-nexus-accent-text">Sign out</button>}>
      {sent && <p role="status" className="flex items-center gap-1.5 text-[13px] text-nexus-success"><CheckCircle2 className="h-4 w-4" aria-hidden /> Sent again.</p>}
      {error && <p role="alert" className="text-[13px] text-nexus-danger">{error}</p>}
      <Button variant="secondary" className="w-full" onClick={() => {
        setError(null);
        authService.resendVerification().then(() => setSent(true), err => setError(getErrorMessage(err)));
      }}>Send it again</Button>
    </AuthCard>
  );
}

/** The app for a signed-in person; otherwise only signing in (or, on a fresh install, creating the owner account). */
export function AuthGate({ children }: { children: ReactNode }) {
  const { user, status } = useAuth();
  const location = useLocation();
  if (!status) {
    return <div className="flex min-h-screen items-center justify-center bg-nexus-bg text-sm text-nexus-text-muted">Loading…</div>;
  }
  if (location.pathname === '/verify-email') return <VerifyEmail />;  // signed in or not
  if (user) {
    // Same rule as the server: only when email can be sent, and never the owner.
    if (status.email && user.emailVerified === false && !user.isAdmin) return <CheckEmail />;
    return (
      <Routes>
        {['/login', '/signup', '/forgot-password', '/reset-password'].map(path => (
          <Route key={path} path={path} element={<Navigate to="/" replace />} />
        ))}
        <Route path="*" element={children} />
      </Routes>
    );
  }
  const start = status.hasUsers ? '/login' : '/signup';
  return (
    <Routes>
      <Route path="/login" element={status.hasUsers ? <AuthPage mode="login" /> : <Navigate to="/signup" replace />} />
      <Route path="/signup" element={status.signupsOpen ? <AuthPage mode="signup" /> : <Navigate to="/login" replace />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="*" element={<Navigate to={start} replace />} />
    </Routes>
  );
}
