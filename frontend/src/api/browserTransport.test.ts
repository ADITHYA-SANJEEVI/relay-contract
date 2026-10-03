import { afterEach, describe, expect, it, vi } from 'vitest';
import { browserTransport, type R1Capabilities } from './browserTransport';
import { RelayApiError } from './client';

const capabilities: R1Capabilities = {
  as_of: '2026-10-03T12:00:00Z', snapshot_scope: 'request_repeatable_read',
  api_revision: 'r1_operator_visibility_v1', database_revision: '0003_operator_indexes',
  authentication: 'existing_local_operator_bearer',
  capabilities: ['BV10_BROWSER_AUTH', 'BV01_JOBS_CATALOGUE'].map(id => ({ id, state: 'AVAILABLE', routes: [], reason: null })),
};
function response(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { 'X-Request-Id': 'backend-request' } });
}
afterEach(() => vi.unstubAllGlobals());

describe('unused browser transport', () => {
  it('uses a fixed same-origin cookie path without bearer or persistence', async () => {
    const fetch = vi.fn().mockResolvedValue(response(capabilities));
    vi.stubGlobal('fetch', fetch);
    const result = await browserTransport.capabilities();
    expect(result.data).toEqual(capabilities);
    expect(result.requestId).toBe('backend-request');
    expect(fetch).toHaveBeenCalledWith('/board-api/operator/capabilities', {
      method: 'GET', credentials: 'same-origin', cache: 'no-store', redirect: 'error', headers: { 'X-Relay-Board': '1' },
    });
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
  it('keeps bootstrap only in a bounded POST body and logout uses DELETE', async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(response({ authenticated: true, mode: 'local_read_session', expires_in_seconds: 1800 })));
    vi.stubGlobal('fetch', fetch);
    await browserTransport.pair('one-use-local-code');
    expect(fetch.mock.calls[0][0]).toBe('/board-api/session');
    expect(fetch.mock.calls[0][1].method).toBe('POST');
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ pairing_code: 'one-use-local-code' });
    await browserTransport.session();
    await browserTransport.logout();
    expect(fetch.mock.calls[1][1].method).toBe('GET');
    expect(fetch.mock.calls[2][1].method).toBe('DELETE');
  });
  it.each([401, 404, 409, 422, 503])('retains typed backend %s errors and request IDs', async status => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ error: {
      code: 'backend_code', message: 'backend_message', retryable: status === 503,
      outcome: 'rejected', request_id: 'body-request', details: { evidence: 'preserved' },
    } }, status)));
    await expect(browserTransport.jobs()).rejects.toMatchObject({ status, code: 'backend_code', retryable: status === 503,
      requestId: 'backend-request', details: { evidence: 'preserved' }, outcome: 'rejected' });
  });
  it('preserves bigint strings, observation, cursors and verification failure without transformation', async () => {
    const evidence = { ...capabilities, next_cursor: '9223372036854775807', accepted_authority: { status: 'ACCEPTED' },
      verification: { state: 'FAILED', code: 'checksum_mismatch' } };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(evidence)));
    expect((await browserTransport.read('artifacts/example/verification')).data).toEqual(evidence);
  });
  it('encodes query parameters and rejects arbitrary upstream/control paths', async () => {
    const fetch = vi.fn().mockResolvedValue(response({ items: [], next_cursor: null }));
    vi.stubGlobal('fetch', fetch);
    await browserTransport.jobs(new URLSearchParams({ cursor: 'a+b', limit: '2' }));
    expect(fetch.mock.calls[0][0]).toBe('/board-api/operator/jobs?cursor=a%2Bb&limit=2');
    for (const path of ['https://elsewhere', '../health', 'jobs/example/cancel', 'artifacts/example/content']) {
      expect(() => browserTransport.read(path)).toThrow('Unsupported');
    }
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('fixture mode is explicit and does not fetch', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    expect(await browserTransport.probe('fixture')).toEqual({ state: 'fixture', isSynthetic: true });
    expect(fetch).not.toHaveBeenCalled();
  });
  it('live mode requires capabilities and a successful harmless read', async () => {
    const jobs = { as_of: capabilities.as_of, snapshot_scope: capabilities.snapshot_scope, items: [], next_cursor: null };
    const fetch = vi.fn().mockResolvedValueOnce(response(capabilities)).mockResolvedValueOnce(response(jobs));
    vi.stubGlobal('fetch', fetch);
    expect(await browserTransport.probe('live')).toEqual({ state: 'live-connected', isSynthetic: false, capabilities, jobs });
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it.each(['DEFERRED', 'UNAVAILABLE', 'UNSUPPORTED'] as const)('keeps %s capability states explicit', async state => {
    const unavailable = { ...capabilities, capabilities: [{ ...capabilities.capabilities[0], state }] };
    const fetch = vi.fn().mockResolvedValue(response(unavailable)); vi.stubGlobal('fetch', fetch);
    expect(await browserTransport.probe('live')).toEqual({ state: 'capability-unavailable', isSynthetic: false, capabilities: unavailable });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it.each([401, 503])('never falls back to fixtures on HTTP %s', async status => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ error: { code: 'unavailable' } }, status)));
    const result = await browserTransport.probe('live');
    expect(result.state).toBe(status === 401 ? 'authentication-required' : 'backend-unavailable');
    expect(result.isSynthetic).toBe(false);
    expect('error' in result && result.error).toBeInstanceOf(RelayApiError);
  });
  it('network and malformed JSON failures stay unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    expect((await browserTransport.probe('live')).state).toBe('backend-unavailable');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('broken')));
    await expect(browserTransport.jobs()).rejects.toMatchObject({ status: 503, code: 'browser_upstream_invalid' });
  });
});
