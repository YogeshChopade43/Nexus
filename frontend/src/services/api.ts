const DEFAULT_BASE_URL = 'http://localhost:8000';

const configuredUrl =
  (typeof import.meta !== 'undefined' && (import.meta.env?.VITE_API_URL || import.meta.env?.VITE_API_BASE_URL)) || '';
// 'same-origin': the backend serves this frontend (the Docker image), so call it on the same address.
const envBaseUrl = configuredUrl === 'same-origin' ? '' : configuredUrl || DEFAULT_BASE_URL;

/** FastAPI returns `detail` as a string, or a list of {msg} objects for validation errors. */
function errorMessage(data: { message?: string; detail?: unknown }, fallback: string): string {
  if (data.message) return data.message;
  if (typeof data.detail === 'string') return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail
      .map((d: { msg?: string }) => (d.msg ?? '').replace(/^Value error, /, ''))
      .filter(Boolean)
      .join('; ') || fallback;
  }
  return fallback;
}

async function failure(response: Response): Promise<ApiError> {
  const errorData = await response.json().catch(() => ({}));
  return { code: `HTTP_${response.status}`, message: errorMessage(errorData, response.statusText), details: errorData };
}

class ApiService {
  private baseUrl: string;
  private defaultHeaders: HeadersInit;

  constructor(baseUrl: string = envBaseUrl) {
    this.baseUrl = baseUrl;
    this.defaultHeaders = {
      'Content-Type': 'application/json',
    };
  }

  setBaseUrl(url: string) {
    this.baseUrl = url;
  }

  getBaseUrl(): string {
    return this.baseUrl;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const headers = {
      ...this.defaultHeaders,
      ...options.headers,
    };

    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (!response.ok) {
      throw await failure(response);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    return response.json();
  }

  async get<T>(endpoint: string, params?: Record<string, string>): Promise<T> {
    const url = params
      ? `${endpoint}?${new URLSearchParams(params).toString()}`
      : endpoint;
    return this.request<T>(url, { method: 'GET' });
  }

  async post<T>(endpoint: string, data?: unknown): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'POST',
      body: data ? JSON.stringify(data) : undefined,
    });
  }

  async put<T>(endpoint: string, data?: unknown): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'PUT',
      body: data ? JSON.stringify(data) : undefined,
    });
  }

  async patch<T>(endpoint: string, data?: unknown): Promise<T> {
    return this.request<T>(endpoint, {
      method: 'PATCH',
      body: data ? JSON.stringify(data) : undefined,
    });
  }

  async delete<T>(endpoint: string): Promise<T> {
    return this.request<T>(endpoint, { method: 'DELETE' });
  }

  async stream<T>(
    endpoint: string,
    data: unknown,
    onChunk: (chunk: T) => void,
    onError?: (error: Error) => void,
    onComplete?: () => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const url = `${this.baseUrl}${endpoint}`;
    const response = await fetch(url, {
      signal,
      method: 'POST',
      headers: this.defaultHeaders,
      body: JSON.stringify(data),
    });

    if (!response.ok) {
      throw await failure(response);
    }

    const reader = response.body?.getReader();
    const decoder = new TextDecoder();

    if (!reader) {
      throw new Error('Response body is not readable');
    }

    let buffer = '';
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        // SSE lines can be split across network chunks; keep the partial tail for the next read.
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines.filter((l) => l.trim())) {
          if (line.startsWith('data: ')) {
            const jsonStr = line.slice(6);
            if (jsonStr === '[DONE]') {
              onComplete?.();
              return;
            }
            try {
              const parsed = JSON.parse(jsonStr);
              onChunk(parsed);
            } catch {
              // Ignore parse errors for incomplete chunks
            }
          }
        }
      }
    } catch (error) {
      onError?.(error as Error);
      throw error;
    } finally {
      reader.releaseLock();
    }
  }
}

export const api = new ApiService();

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}