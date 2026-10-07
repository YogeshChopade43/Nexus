export interface UserSettings {
  theme: 'dark' | 'light' | 'system';
  language: string;
  timezone: string;
  notifications: NotificationSettings;
  privacy: PrivacySettings;
  editor: EditorSettings;
}

export interface NotificationSettings {
  email: boolean;
  push: boolean;
  workflowCompletion: boolean;
  workflowFailure: boolean;
  appUpdates: boolean;
  mentions: boolean;
}

export interface PrivacySettings {
  analytics: boolean;
  crashReporting: boolean;
  dataSharing: boolean;
}

export interface EditorSettings {
  fontSize: number;
  fontFamily: string;
  tabSize: number;
  wordWrap: boolean;
  minimap: boolean;
  lineNumbers: boolean;
}

export interface ApiSettings {
  baseUrl: string;
  timeout: number;
  retries: number;
}

export interface SettingsResponse {
  user: UserSettings;
  api: ApiSettings;
}