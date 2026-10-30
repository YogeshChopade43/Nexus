import { api } from './api';

export interface AuthUser {
  id: number;
  email: string;
  name: string;
  isAdmin: boolean;
  emailVerified?: boolean;
  hasPassword?: boolean;
  /** Signs in with Google. */
  google?: boolean;
}

export interface AuthStatus {
  /** False on a fresh install: the first account becomes its owner. */
  hasUsers: boolean;
  signupsOpen: boolean;
  user: AuthUser | null;
  /** "Continue with Google" is set up. */
  google?: boolean;
  /** Email can be sent (verification, password reset). */
  email?: boolean;
  /** The operator's own privacy policy and terms, linked on the sign-in page ('' = none). */
  privacyUrl?: string;
  termsUrl?: string;
}

/** What the sign-in page asks after the email: its password, Google, a new account, or nothing (sign-ups closed). */
export type LookupNext = 'password' | 'google' | 'create' | 'closed';

export interface AuthSession {
  id: string;
  createdAt: string;
  userAgent: string;
  current: boolean;
}

export const authService = {
  status: () => api.get<AuthStatus>('/api/auth/status'),
  lookup: (email: string) => api.post<{ next: LookupNext }>('/api/auth/lookup', { email }),
  signup: (name: string, email: string, password: string) => api.post<AuthUser>('/api/auth/signup', { name, email, password }),
  login: (email: string, password: string) => api.post<AuthUser>('/api/auth/login', { email, password }),
  logout: () => api.post<void>('/api/auth/logout'),
  googleStartUrl: () => `${api.getBaseUrl()}/api/auth/google/start`,
  forgotPassword: (email: string) => api.post<void>('/api/auth/forgot-password', { email }),
  resetPassword: (token: string, password: string) => api.post<AuthUser>('/api/auth/reset-password', { token, password }),
  verifyEmail: (token: string) => api.post<AuthUser>('/api/auth/verify-email', { token }),
  resendVerification: () => api.post<void>('/api/auth/resend-verification'),
  rename: (name: string) => api.patch<AuthUser>('/api/auth/me', { name }),
  changePassword: (current: string, next: string) => api.post<void>('/api/auth/change-password', { current, new: next }),
  sessions: () => api.get<AuthSession[]>('/api/auth/sessions'),
  endSession: (id: string) => api.delete<void>(`/api/auth/sessions/${encodeURIComponent(id)}`),
  exportUrl: () => `${api.getBaseUrl()}/api/auth/export`,
  deleteAccount: (password: string) => api.delete<void>('/api/auth/me', { password }),
};
