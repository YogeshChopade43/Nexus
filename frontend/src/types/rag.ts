export interface Library {
  id: number;
  name: string;
  kind: 'library';
  documents: number;
  ready: number;
  created_at: string;
}

export type DocumentStatus = 'queued' | 'processing' | 'ready' | 'failed';

export interface RagDocument {
  id: number;
  collection_id: number;
  name: string;
  mime: string;
  size_bytes: number;
  version: number;
  status: DocumentStatus;
  /** Why it failed; also notes like "waiting for search model" or "re-upload recommended". */
  error: string | null;
  progress: number;
  pages: number | null;
  chars: number;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

/** A retrieved passage (a document section). */
export interface Passage {
  chunk_id: number;
  document_id: number;
  document_name: string;
  text: string;
  heading_path: string;
  page_start: number | null;
  page_end: number | null;
  score: number;
}

export interface SearchResult {
  sources: Passage[];
  insufficient: boolean;
  keyword_only: boolean;
  log_id: number | null;
}

export interface ChunkView {
  chunk: { id: number; document_id: number; document_name: string; text: string; heading_path: string;
    page_start: number | null; page_end: number | null };
  before: { id: number; text: string } | null;
  after: { id: number; text: string } | null;
}

export interface RagStatus {
  models_ready: boolean;
  vector_backend: 'sqlite-vec' | 'python';
  queue: Record<'queued' | 'running' | 'retry', number>;
  documents: Record<DocumentStatus, number>;
}

/** A source cited as [n] in an answer. */
export interface Citation {
  n: number;
  document_id: number;
  document_name: string;
  heading_path: string;
  pages: string;
  chunk_id: number;
  snippet: string;
}
