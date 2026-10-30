import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Check, CheckCircle2, Eye, EyeOff, MailCheck } from 'lucide-react';
import { Logo } from '../components/layout/Sidebar';
import { Button } from '../components/ui/Button';
import { fieldClass } from '../components/ui/Input';
import { useAuth } from '../hooks/useAuth';
import { authService, type LookupNext } from '../services/auth';
import { cn, getErrorMessage } from '../lib/utils';

const MIN_PASSWORD = 10;

/** The checks the server also enforces, shown live so people pass on the first try. */
const passwordRules = (pw: string) => [
  { ok: pw.length >= MIN_PASSWORD, label: `At least ${MIN_PASSWORD} characters` },
  { ok: new Set(pw).size >= 5, label: 'A mix of different characters' },
];
const passwordOk = (pw: string) => passwordRules(pw).every(r => r.ok);
const passwordProblem = (pw: string) => (pw.length < MIN_PASSWORD
  ? `At least ${MIN_PASSWORD} characters for your password, please.`
  : 'Use a wider mix of characters in your password.');

/** What Nexus does, on the brand half of the sign-in page. */
const POINTS = ['Automate repetitive work with workflows', 'Connect the apps you already use', 'Ask questions about your own documents'];

/** The brand half of the sign-in page (wide screens only). */
function BrandPanel() {
  return (
    <aside className="relative hidden overflow-hidden border-r border-nexus-border bg-nexus-bg-secondary p-12 lg:flex lg:flex-col lg:justify-between">
      <div aria-hidden className="pointer-events-none absolute -left-40 -top-40 h-[28rem] w-[28rem] rounded-full bg-[#3B5BFF]/15 blur-3xl" />
      <div aria-hidden className="pointer-events-none absolute -bottom-48 -right-24 h-[26rem] w-[26rem] rounded-full bg-nexus-accent/10 blur-3xl" />
      <div className="relative flex items-center gap-2.5">
        <Logo className="h-8 w-8" />
        <span className="font-brand text-xl tracking-tight text-nexus-text">
          <span className="font-semibold">Nexus</span> <span className="font-light">AI</span>
        </span>
      </div>
      <div className="relative max-w-md space-y-8">
        <p className="font-brand text-[2rem] font-semibold leading-tight tracking-tight text-nexus-text">
          Your AI agent for chats, workflows, apps and documents.
        </p>
        <ul className="space-y-4">
          {POINTS.map(point => (
            <li key={point} className="flex items-center gap-3 text-[15px] text-nexus-text-secondary">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-nexus-accent/15 text-nexus-accent-text">
                <Check className="h-3.5 w-3.5" aria-hidden />
              </span>
              {point}
            </li>
          ))}
        </ul>
      </div>
      <p className="relative text-xs text-nexus-text-muted">Every account&apos;s chats, apps and files are private to it.</p>
    </aside>
  );
}

/** One sign-in screen: beside the brand panel on wide screens; on phones, just the logo above it. */
function AuthScreen({ title, subtitle, children, footer }: { title: string; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="grid min-h-screen bg-nexus-bg lg:grid-cols-2">
      <BrandPanel />
      <main className="flex items-center justify-center px-6 py-12 sm:px-10">
        <div className="w-full max-w-sm space-y-7">
          <div className="space-y-2">
            <Logo className="mb-8 h-9 w-9 lg:hidden" />
            <h1 className="text-2xl font-semibold tracking-tight text-nexus-text">{title}</h1>
            {subtitle && <p className="text-sm leading-relaxed text-nexus-text-secondary">{subtitle}</p>}
          </div>
          <div className="space-y-4">{children}</div>
          {footer && <p className="text-[13px] text-nexus-text-secondary">{footer}</p>}
        </div>
      </main>
    </div>
  );
}

function Field({ label, hint, ...input }: { label: string; hint?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block space-y-1.5">
      <span className="block text-[13px] font-medium text-nexus-text">{label}</span>
      <input aria-label={label} className={cn(fieldClass, 'h-10')} {...input} />
      {hint && <span className="block text-xs text-nexus-text-muted">{hint}</span>}
    </label>
  );
}

/** A password input with a show/hide toggle and a Caps-Lock heads-up. */
function PasswordField({ label, value, onChange, autoComplete, autoFocus }: {
  label: string; value: string; onChange: (v: string) => void; autoComplete: string; autoFocus?: boolean;
}) {
  const [show, setShow] = useState(false);
  const [caps, setCaps] = useState(false);
  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => setCaps(e.getModifierState?.('CapsLock') ?? false);
  return (
    <label className="block space-y-1.5">
      <span className="block text-[13px] font-medium text-nexus-text">{label}</span>
      <span className="relative block">
        <input aria-label={label} type={show ? 'text' : 'password'} className={cn(fieldClass, 'h-10 pr-10')} value={value}
          onChange={(e) => onChange(e.target.value)} onKeyUp={onKey} onKeyDown={onKey} autoComplete={autoComplete}
          autoFocus={autoFocus} required />
        <button type="button" onClick={() => setShow((s) => !s)} aria-pressed={show}
          aria-label={show ? 'Hide password' : 'Show password'} tabIndex={-1}
          className="absolute inset-y-0 right-0 flex items-center px-3 text-nexus-text-muted hover:text-nexus-text">
          {show ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
        </button>
      </span>
      {caps && <span role="status" className="block text-xs text-nexus-warning">Caps Lock is on.</span>}
    </label>
  );
}

function PasswordChecklist({ value }: { value: string }) {
  return (
    <ul className="space-y-1" aria-label="Password requirements">
      {passwordRules(value).map((rule) => (
        <li key={rule.label} className={cn('flex items-center gap-1.5 text-xs', rule.ok ? 'text-nexus-success' : 'text-nexus-text-muted')}>
          {rule.ok ? <Check className="h-3.5 w-3.5 shrink-0" aria-hidden />
            : <span className="h-3.5 w-3.5 shrink-0 rounded-full border border-current" aria-hidden />}
          {rule.label}
        </li>
      ))}
    </ul>
  );
}

function GoogleButton() {
  return (
    <a href={authService.googleStartUrl()}
      className="flex h-10 w-full items-center justify-center gap-2 rounded-md border border-nexus-border bg-nexus-bg-secondary text-sm font-medium text-nexus-text shadow-surface transition-colors hover:bg-nexus-bg-tertiary hover:no-underline">
      <span aria-hidden className="bg-[conic-gradient(from_-45deg,#ea4335_0_25%,#4285f4_0_50%,#34a853_0_75%,#fbbc05_0)] bg-clip-text text-base font-bold text-transparent">G</span>
      Continue with Google
    </a>
  );
}

const OrDivider = () => (
  <div className="flex items-center gap-3 text-[11px] uppercase tracking-wider text-nexus-text-muted">
    <span className="h-px flex-1 bg-nexus-border" />or<span className="h-px flex-1 bg-nexus-border" />
  </div>
);

const ErrorText = ({ children }: { children: ReactNode }) => <p role="alert" className="text-[13px] text-nexus-danger">{children}</p>;

/** The email being signed in with, and the way back to change it. */
function EmailRow({ email, onChange }: { email: string; onChange: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-nexus-border bg-nexus-bg-secondary px-3 py-2.5">
      <span className="truncate text-sm text-nexus-text">{email}</span>
      <button type="button" onClick={onChange} aria-label="Change email"
        className="shrink-0 text-[13px] font-medium text-nexus-accent-text hover:underline">Change</button>
    </div>
  );
}

/** The operator's own terms and privacy policy, when the admin has linked them (Settings › Admin). */
function PolicyLinks() {
  const { status } = useAuth();
  const links = ([['Terms', status?.termsUrl], ['Privacy Policy', status?.privacyUrl]] as const).filter(([, href]) => href);
  if (!links.length) return null;
  return (
    <p className="text-xs leading-relaxed text-nexus-text-muted">
      By continuing, you agree to the{' '}
      {links.map(([label, href], i) => (
        <span key={label}>
          {i > 0 && ' and '}
          <a href={href} target="_blank" rel="noopener noreferrer" className="text-nexus-accent-text">{label}</a>
        </span>
      ))}
      .
    </p>
  );
}

/** Password managers save and fill the email with the password only when the form carries it. */
const Username = ({ email }: { email: string }) => <input type="email" name="username" autoComplete="username" value={email} readOnly hidden />;

/** Sign in or create an account: the email first, then what that email needs. */
function SignIn() {
  const { login, signup, status } = useAuth();
  const [params] = useSearchParams();
  const [step, setStep] = useState<'email' | LookupNext>('email');
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(params.get('error'));  // e.g. back from Google
  const [busy, setBusy] = useState(false);
  const address = email.trim();

  const attempt = async (work: () => Promise<unknown>) => {
    setError(null);
    setBusy(true);
    try {
      await work();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  const back = () => {
    setStep('email');
    setPassword('');
    setError(null);
  };
  const submit = (work: () => Promise<unknown>) => (e: FormEvent) => {
    e.preventDefault();
    void attempt(work);
  };

  if (step === 'email') {
    return (
      <AuthScreen title="Welcome to Nexus" subtitle="Sign in, or create an account if you’re new.">
        {status?.google && <><GoogleButton /><OrDivider /></>}
        <form onSubmit={submit(async () => setStep((await authService.lookup(address)).next))} className="space-y-4">
          <Field label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" autoFocus required />
          {error && <ErrorText>{error}</ErrorText>}
          <Button type="submit" size="lg" className="w-full" loading={busy}>Continue</Button>
        </form>
        <PolicyLinks />
      </AuthScreen>
    );
  }

  if (step === 'password') {
    return (
      <AuthScreen title="Welcome back" subtitle="Enter your password to sign in.">
        <EmailRow email={address} onChange={back} />
        <form onSubmit={submit(() => login(address, password))} className="space-y-4">
          <Username email={address} />
          <PasswordField label="Password" value={password} onChange={setPassword} autoComplete="current-password" autoFocus />
          {status?.email && (
            <div className="-mt-1 text-right">
              <Link to="/forgot-password" state={{ email: address }} className="text-xs text-nexus-accent-text">Forgot password?</Link>
            </div>
          )}
          {error && <ErrorText>{error}</ErrorText>}
          <Button type="submit" size="lg" className="w-full" loading={busy}>Sign in</Button>
        </form>
      </AuthScreen>
    );
  }

  if (step === 'create') {
    const create = (e: FormEvent) => {
      e.preventDefault();
      if (!passwordOk(password)) {
        setError(passwordProblem(password));
        return;
      }
      void attempt(() => signup(name.trim(), address, password));
    };
    return (
      <AuthScreen title="Create your account" subtitle={status?.hasUsers === false
        ? 'You’re the first here, so this account will own this Nexus.'
        : 'No account for this email yet. Create one to get started.'}>
        <EmailRow email={address} onChange={back} />
        <form onSubmit={create} className="space-y-4">
          <Username email={address} />
          <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" maxLength={80} autoFocus />
          <PasswordField label="Password" value={password} onChange={setPassword} autoComplete="new-password" />
          {password.length > 0 && <PasswordChecklist value={password} />}
          {error && <ErrorText>{error}</ErrorText>}
          <Button type="submit" size="lg" className="w-full" loading={busy}>Create account</Button>
        </form>
        <PolicyLinks />
      </AuthScreen>
    );
  }

  if (step === 'google') {
    return (
      <AuthScreen title="Sign in with Google" subtitle="This account signs in with Google.">
        <EmailRow email={address} onChange={back} />
        {status?.google ? <GoogleButton />
          : <p className="text-[13px] text-nexus-text-secondary">Google sign-in isn’t set up on this Nexus right now. Ask its owner for help.</p>}
        {status?.email && (
          <p className="text-[13px] text-nexus-text-secondary">
            Or <Link to="/forgot-password" state={{ email: address }} className="text-nexus-accent-text">set a password</Link> for this account.
          </p>
        )}
      </AuthScreen>
    );
  }

  return (
    <AuthScreen title="No account for this email" subtitle="Sign-ups are closed on this Nexus. Ask its owner for an account, or use another email.">
      <EmailRow email={address} onChange={back} />
    </AuthScreen>
  );
}

function ForgotPassword() {
  const location = useLocation();
  const [email, setEmail] = useState(() => (location.state as { email?: string } | null)?.email ?? '');  // from sign-in
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
    <AuthScreen title="Reset your password" subtitle={sent ? undefined : 'We’ll email you a link to choose a new one.'}
      footer={<Link to="/login" className="text-nexus-accent-text">Back to sign in</Link>}>
      {sent ? (
        <p role="status" className="flex items-start gap-2 text-[13px] text-nexus-text-secondary">
          <MailCheck className="mt-0.5 h-4 w-4 shrink-0 text-nexus-accent-text" aria-hidden />
          If there&apos;s an account for {sent}, we&apos;ve sent it a link to choose a new password. It works for an hour.
        </p>
      ) : (
        <form onSubmit={(e) => void submit(e)} className="space-y-4">
          <Field label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required />
          <Button type="submit" size="lg" className="w-full" loading={busy}>Send reset link</Button>
        </form>
      )}
    </AuthScreen>
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
    if (!passwordOk(password)) {
      setError(passwordProblem(password));
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
    <AuthScreen title="Choose a new password" subtitle="This signs you out on your other devices."
      footer={<Link to="/forgot-password" className="text-nexus-accent-text">Need a new link?</Link>}>
      <form onSubmit={(e) => void submit(e)} className="space-y-4">
        <PasswordField label="New password" value={password} onChange={setPassword} autoComplete="new-password" autoFocus />
        {password.length > 0 && <PasswordChecklist value={password} />}
        {error && <ErrorText>{error}</ErrorText>}
        <Button type="submit" size="lg" className="w-full" loading={busy}>Set new password</Button>
      </form>
    </AuthScreen>
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
    <AuthScreen title="Confirming your email…" footer={<Link to="/" className="text-nexus-accent-text">Go to Nexus</Link>}>
      {error ? <ErrorText>{error}</ErrorText> : <p className="text-[13px] text-nexus-text-muted">One moment.</p>}
    </AuthScreen>
  );
}

/** Signed in, but the email still has to be confirmed before using Nexus. */
function CheckEmail() {
  const { user, logout } = useAuth();
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);  // seconds until "Send it again" is allowed (rate-limited server-side)
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);
  const resend = () => {
    setError(null);
    authService.resendVerification().then(() => { setSent(true); setCooldown(30); }, (err) => setError(getErrorMessage(err)));
  };
  return (
    <AuthScreen title="Check your email" subtitle={<>We sent a link to <b className="text-nexus-text">{user?.email}</b>. Open it to start using Nexus.</>}
      footer={<button type="button" onClick={() => void logout()} className="text-nexus-accent-text">Sign out</button>}>
      {sent && <p role="status" className="flex items-center gap-1.5 text-[13px] text-nexus-success"><CheckCircle2 className="h-4 w-4" aria-hidden /> Sent again.</p>}
      {error && <ErrorText>{error}</ErrorText>}
      <Button variant="secondary" size="lg" className="w-full" disabled={cooldown > 0} onClick={resend}>
        {cooldown > 0 ? `Send it again in ${cooldown}s` : 'Send it again'}
      </Button>
    </AuthScreen>
  );
}

/** The app for a signed-in person; otherwise signing in, which also creates accounts (the first one owns the Nexus). */
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
  return (
    <Routes>
      <Route path="/login" element={<SignIn />} />
      <Route path="/signup" element={<SignIn />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
