import { api } from './api';
import type { UserSettings, ApiSettings, ConnectedAccount, SettingsResponse } from '../types/settings';

export const settingsService = {
  async getSettings(): Promise<SettingsResponse> {
    return api.get<SettingsResponse>('/api/settings');
  },

  async updateUserSettings(settings: Partial<UserSettings>): Promise<UserSettings> {
    return api.patch<UserSettings>('/api/settings/user', settings);
  },

  async updateApiSettings(settings: Partial<ApiSettings>): Promise<ApiSettings> {
    return api.patch<ApiSettings>('/api/settings/api', settings);
  },

  async getConnectedAccounts(): Promise<ConnectedAccount[]> {
    const response = await api.get<{ accounts: ConnectedAccount[] }>('/api/settings/accounts');
    return response.accounts;
  },

  async disconnectAccount(accountId: string): Promise<void> {
    return api.delete<void>(`/api/settings/accounts/${accountId}`);
  },
};