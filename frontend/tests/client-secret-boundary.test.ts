import { spawnSync } from 'node:child_process';
import { describe, expect, it } from 'vitest';

describe('client build secret boundary', () => {
  it('rejects a client-visible secret variable without printing its value', () => {
    const probe = 'ephemeral-build-probe';
    const result = spawnSync(process.execPath, ['scripts/check-client-secrets.js'], {
      env: { ...process.env, VITE_OPERATOR_PASSWORD: probe }, encoding: 'utf8',
    });
    expect(result.status).toBe(1);
    expect(result.stderr).toContain('Client secret environment variable rejected');
    expect(result.stdout + result.stderr).not.toContain(probe);
  });
  it('detects server credential bytes in a client file without printing them', () => {
    // Safe existing client text acts as the test credential; no credential fixture/file.
    const probe = 'Unsupported R1 browser read route';
    const result = spawnSync(process.execPath, ['scripts/check-client-secrets.js'], {
      env: { ...process.env, RELAY_OPERATOR_TOKEN: probe }, encoding: 'utf8',
    });
    expect(result.status).toBe(1);
    expect(result.stderr).toContain('Server-only material in client file:');
    expect(result.stdout + result.stderr).not.toContain(probe);
  });
});
