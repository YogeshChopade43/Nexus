import { api } from './api';
import type { AuthUser } from './auth';

export interface AdminUser extends AuthUser {
  disabled: boolean;
  createdAt: string;
  tokens30d: number;
  storageBytes: number;
}

export interface InstanceSettings {
  /** null: the server's NEXUS_SIGNUPS decides. */
  signups: 'open' | 'closed' | null;
  /** Per person, admins exempt; 0 = no limit. */
  storageLimitMb: number;
}

export interface DeploymentCheck {
  id: string;
  title: string;
  ok: boolean;
  detail: string;
}

export const adminService = {
  users: () => api.get<AdminUser[]>('/api/admin/users'),
  changeUser: (id: number, changes: { disabled?: boolean; isAdmin?: boolean }) => api.patch<AdminUser>(`/api/admin/users/${id}`, changes),
  instance: () => api.get<InstanceSettings>('/api/admin/instance'),
  changeInstance: (changes: Partial<InstanceSettings>) => api.patch<InstanceSettings>('/api/admin/instance', changes),
  deployment: () => api.get<DeploymentCheck[]>('/api/admin/deployment'),
};
