export interface Memory {
  id: number;
  content: string;
  created_at: string;
  /** "auto": learned from a chat by itself; "manual": the user asked or added it. */
  source?: 'auto' | 'manual';
}
