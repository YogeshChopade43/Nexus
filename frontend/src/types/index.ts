export * from './app';
export * from './chat';
export * from './workflow';

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}
