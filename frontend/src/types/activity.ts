export type ActivityType =
  | 'message_sent'
  | 'message_received'
  | 'app_connected'
  | 'app_disconnected'
  | 'workflow_created'
  | 'workflow_updated'
  | 'workflow_deleted'
  | 'workflow_executed'
  | 'workflow_completed'
  | 'workflow_failed'
  | 'workflow_resumed'
  | 'server_error'
  | 'document_failed'
  | 'reminder'
  | 'will_armed'
  | 'will_ran'
  | 'run_once_set'
  | 'run_once_ran'
  | 'settings_changed'
  | 'action_approved'
  | 'action_undone';

/** The call that reverses an approved action, proposed by the AI for the user to confirm. */
export interface UndoPlan {
  tool: string;
  arguments: Record<string, unknown>;
  explanation: string;
}

export interface Activity {
  id: string;
  type: ActivityType;
  title: string;
  description: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
  userId: string;
}

export interface ActivityFilter {
  types?: ActivityType[];
  dateFrom?: string;
  dateTo?: string;
  limit?: number;
  offset?: number;
}

export interface ActivityResponse {
  activities: Activity[];
  total: number;
  hasMore: boolean;
}