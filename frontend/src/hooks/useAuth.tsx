import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { authService, type AuthStatus, type AuthUser } from '../services/auth';

interface AuthContextValue {
  user: AuthUser | null;
  /** null while loading. */
  status: AuthStatus | null;
  login: (email: string, password: string) => Promise<void>;
  signup: (name: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Signed in by a link (reset password, verify email) or after changing the account. */
  signedIn: (user: AuthUser) => void;
  signedOut: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/** Who is signed in. Any 401 from the API (an expired or ended session) signs the app out ("nexus:signed-out"). */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus | null>(null);

  const refresh = useCallback(() => {
    authService.status().then(setStatus).catch(() => setStatus({ hasUsers: true, signupsOpen: false, user: null }));
  }, []);
  useEffect(refresh, [refresh]);
  useEffect(() => {
    const signedOut = () => setStatus(prev => (prev ? { ...prev, user: null } : prev));
    window.addEventListener('nexus:signed-out', signedOut);
    return () => window.removeEventListener('nexus:signed-out', signedOut);
  }, []);

  const signedIn = (user: AuthUser) => setStatus(prev => ({ ...prev, hasUsers: true, signupsOpen: prev?.signupsOpen ?? false, user }));
  const value: AuthContextValue = {
    user: status?.user ?? null,
    status,
    login: async (email, password) => signedIn(await authService.login(email, password)),
    signup: async (name, email, password) => {
      signedIn(await authService.signup(name, email, password));
      refresh();  // sign-ups may have closed now (the first account is the owner)
    },
    logout: async () => {
      await authService.logout().catch(() => {});
      setStatus(prev => (prev ? { ...prev, user: null } : prev));
    },
    signedIn,
    signedOut: () => setStatus(prev => (prev ? { ...prev, user: null } : prev)),
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside AuthProvider');
  return value;
}
