/** Slice 2 infrastructure only. Fixed same-origin cookie transport; no bearer input. */
import { RelayApiError, type ApiErrorDetails } from './client';

export type CapabilityAvailability = 'AVAILABLE' | 'UNAVAILABLE' | 'DEFERRED' | 'UNSUPPORTED';
export interface R1Observation {
  as_of: string;
  snapshot_scope: 'request_repeatable_read';
}
export interface R1Capabilities extends R1Observation {
  api_revision: 'r1_operator_visibility_v1';
  database_revision: string;
  /** Upstream authentication; browser authentication is described by LocalSession. */
  authentication: 'existing_local_operator_bearer';
  capabilities: { id: string; state: CapabilityAvailability; routes: string[]; reason: string | null }[];
}
export interface R1Job {
  id: string;
  definition_hash: string;
  workload_name: string;
  workload_version: string;
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED';
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  partition_count: string;
  attempt_count: string;
  partition_counts: Record<'READY' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED', string>;
  next_event_seq: string;
  partial_result_count: string;
  complete: boolean;
}
export interface R1Jobs extends R1Observation { items: R1Job[]; next_cursor: string | null }
export interface LocalSession {
  authenticated: true;
  mode: 'local_read_session';
  expires_in_seconds: number;
}
export interface BrowserResponse<T> { data: T; requestId: string | null }
export type BrowserConnection =
  | { state: 'fixture'; isSynthetic: true }
  | { state: 'live-connected'; isSynthetic: false; capabilities: R1Capabilities; jobs: R1Jobs }
  | { state: 'authentication-required' | 'backend-unavailable'; isSynthetic: false; error: RelayApiError }
  | { state: 'capability-unavailable'; isSynthetic: false; capabilities: R1Capabilities };

const routes = /^(capabilities|jobs|workers|(?:jobs|workers|partitions|attempts|artifacts)\/[A-Za-z0-9-]{1,64}|jobs\/[A-Za-z0-9-]{1,64}\/(?:partitions|result-metadata|events|definition)|workers\/[A-Za-z0-9-]{1,64}\/(?:attempts|events)|partitions\/[A-Za-z0-9-]{1,64}\/history|artifacts\/[A-Za-z0-9-]{1,64}\/verification)$/;

async function request<T>(path: string, method = 'GET', body?: object): Promise<BrowserResponse<T>> {
  let response: Response;
  try {
    response = await fetch('/board-api/' + path, {
      method, credentials: 'same-origin', cache: 'no-store', redirect: 'error',
      headers: { 'X-Relay-Board': '1', ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
  } catch {
    throw new RelayApiError(503, { code: 'browser_backend_unavailable', retryable: true, outcome: 'not_committed' });
  }
  const requestId = response.headers.get('X-Request-Id');
  let data: T & { error?: ApiErrorDetails };
  try { data = await response.json(); }
  catch {
    throw new RelayApiError(503, { code: 'browser_upstream_invalid', request_id: requestId, outcome: 'not_committed' });
  }
  if (!response.ok) {
    throw new RelayApiError(response.status, { ...data.error, request_id: requestId || data.error?.request_id });
  }
  return { data, requestId };
}

export const browserTransport = {
  pair: (pairingCode: string) => request<LocalSession>('session', 'POST', { pairing_code: pairingCode }),
  session: () => request<LocalSession>('session'),
  logout: () => request<{ authenticated: false; mode: 'local_read_session' }>('session', 'DELETE'),
  read<T>(path: string, query?: URLSearchParams): Promise<BrowserResponse<T>> {
    if (!routes.test(path)) throw new Error('Unsupported R1 browser read route');
    const suffix = query?.toString();
    return request<T>('operator/' + path + (suffix ? '?' + suffix : ''));
  },
  capabilities: () => request<R1Capabilities>('operator/capabilities'),
  jobs: (query?: URLSearchParams) => browserTransport.read<R1Jobs>('jobs', query),
  async probe(mode: 'fixture' | 'live'): Promise<BrowserConnection> {
    if (mode === 'fixture') return { state: 'fixture', isSynthetic: true };
    try {
      const { data: capabilities } = await browserTransport.capabilities();
      if (['BV10_BROWSER_AUTH', 'BV01_JOBS_CATALOGUE'].some(id =>
        capabilities.capabilities.find(item => item.id === id)?.state !== 'AVAILABLE')) {
        return { state: 'capability-unavailable', isSynthetic: false, capabilities };
      }
      const { data: jobs } = await browserTransport.jobs();
      return { state: 'live-connected', isSynthetic: false, capabilities, jobs };
    } catch (error) {
      const failure = error instanceof RelayApiError ? error : new RelayApiError(503, { code: 'browser_upstream_invalid' });
      return { state: failure.status === 401 ? 'authentication-required' : 'backend-unavailable',
        isSynthetic: false, error: failure };
    }
  },
};
