/**
 * Relay HTTP Client with exact error mapping and authority preservation.
 */

export interface ApiErrorDetails {
  code: string;
  message: string;
  retryable: boolean;
  outcome: 'committed' | 'not_committed' | 'unknown' | 'rejected';
  request_id?: string | null;
  details?: Record<string, unknown>;
}

export class RelayApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryable: boolean;
  readonly outcome: string;
  readonly requestId: string | null;
  readonly details: Record<string, unknown>;

  constructor(status: number, errorData: Partial<ApiErrorDetails>) {
    super(errorData.message || errorData.code || `HTTP ${status}`);
    this.name = 'RelayApiError';
    this.status = status;
    this.code = errorData.code || (status === 404 ? 'not_found' : 'unknown_error');
    this.retryable = errorData.retryable ?? (status === 503);
    this.outcome = errorData.outcome || 'unknown';
    this.requestId = errorData.request_id || null;
    this.details = errorData.details || {};
  }
}

export interface RequestOptions extends RequestInit {
  token?: string;
}

export async function relayFetch<T>(url: string, options: RequestOptions = {}): Promise<{ data: T; asOf: string; requestId: string | null }> {
  const headers = new Headers(options.headers || {});
  
  if (options.token) {
    headers.set('Authorization', `Bearer ${options.token}`);
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  const asOf = new Date().toISOString();
  const requestId = response.headers.get('X-Request-Id');

  if (!response.ok) {
    let errorData: Partial<ApiErrorDetails> = {};
    try {
      const json = await response.json();
      if (json && json.error) {
        errorData = json.error;
      }
    } catch {
      // not JSON
      errorData = {
        code: response.status === 404 ? 'not_found' : response.status === 401 ? 'unauthenticated' : 'http_error',
        message: response.statusText,
      };
    }
    throw new RelayApiError(response.status, {
      ...errorData,
      request_id: requestId || errorData.request_id,
    });
  }

  const data = await response.json();
  return { data, asOf, requestId };
}
