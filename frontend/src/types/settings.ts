export interface UserSettings {
  theme: 'dark' | 'light' | 'system';
  language: string;
  timezone: string;
  notifications: NotificationSettings;
  privacy: PrivacySettings;
  editor: EditorSettings;
  /** Runs and activity older than this are deleted daily; 0 keeps everything. */
  retentionDays: number;
  notificationsReadAt: string | null;
  /** AI tokens per day (UTC) across chat and workflows; 0 = no limit. */
  dailyTokenLimit: number;
  /** US$ per million tokens, by model name. */
  llmPrices: Record<string, { input: number; output: number }>;
  /** Re-score document search results with the local reranker. */
  ragRerank: boolean;
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