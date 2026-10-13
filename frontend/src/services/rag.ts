import { api } from './api';
import type { ChunkView, Library, RagDocument, RagStatus, SearchResult } from '../types/rag';

/** Multipart upload (the JSON api helper can't send files). */
export async function uploadFiles<T = RagDocument[]>(endpoint: string, files: File[]): Promise<T> {
  const form = new FormData();
  for (const file of files) form.append('file', file, file.name);
  const response = await fetch(`${api.getBaseUrl()}${endpoint}`, { method: 'POST', body: form });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw { code: `HTTP_${response.status}`, message: typeof body.detail === 'string' ? body.detail : response.statusText };
  }
  return body as T;
}

export const ragService = {
  collections: () => api.get<Library[]>('/api/rag/collections'),
  createCollection: (name: string) => api.post<Library>('/api/rag/collections', { name }),
  renameCollection: (id: number, name: string) => api.patch<Library>(`/api/rag/collections/${id}`, { name }),
  deleteCollection: (id: number) => api.delete<void>(`/api/rag/collections/${id}`),
  documents: (collectionId: number) => api.get<RagDocument[]>(`/api/rag/collections/${collectionId}/documents`),
  upload: (collectionId: number, files: File[]) => uploadFiles(`/api/rag/collections/${collectionId}/documents`, files),
  /** Files attached in a chat: searchable only in that conversation. */
  uploadToChat: (sessionId: string, files: File[]) => uploadFiles(`/api/rag/chats/${encodeURIComponent(sessionId)}/documents`, files),
  document: (id: number) => api.get<RagDocument>(`/api/rag/documents/${id}`),
  deleteDocument: (id: number) => api.delete<void>(`/api/rag/documents/${id}`),
  retryDocument: (id: number) => api.post<RagDocument>(`/api/rag/documents/${id}/retry`),
  moveDocument: (id: number, collectionId: number) => api.post<RagDocument>(`/api/rag/documents/${id}/move`, { collection_id: collectionId }),
  chunk: (documentId: number, chunkId: number) => api.get<ChunkView>(`/api/rag/documents/${documentId}/chunks/${chunkId}`),
  search: (query: string, collectionIds?: number[]) =>
    api.post<SearchResult>('/api/rag/search', { query, collection_ids: collectionIds ?? null }),
  status: () => api.get<RagStatus>('/api/rag/status'),
};

export const settled = (doc: RagDocument) => doc.status === 'ready' || doc.status === 'failed';
