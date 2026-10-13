export interface UserSettings {
  theme: 'dark' | 'light' | 'system';
  timezone: string;
  notifications: NotificationSettings;
  /** Runs and activity older than this are deleted daily; 0 keeps everything. */
  retentionDays: number;
  notificationsReadAt: string | null;
  /** AI tokens per day (UTC) across chat and workflows; 0 = no limit. */
  dailyTokenLimit: number;
  /** US$ per million tokens, by model name. */
  llmPrices: Record<string, { input: number; output: number }>;
  /** Re-score document search results with the local reranker. */
  ragRerank: boolean;
  /** Learn lasting facts from chats automatically. */
  memory?: { auto: boolean };
}

export interface NotificationSettings {
  /** Failed workflow runs show in the notification bell. */
  workflowFailure: boolean;
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