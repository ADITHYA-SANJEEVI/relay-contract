import React from 'react';
import { useRelay } from '../context/RelayContext';
import { SCENARIO_WORKERS } from '../fixtures/scenarios';
import { ObservationBadge } from '../components/common/StatusBadges';
import { CopyField } from '../components/common/CopyField';
import { CapabilityUnavailable } from '../components/common/CapabilityUnavailable';

export const WorkersView: React.FC = () => {
  const { isSynthetic, liveAdapter } = useRelay();

  if (!isSynthetic) {
    const gap = liveAdapter.getFleetGap();
    return (
      <CapabilityUnavailable
        capability={gap}
        type="gap"
      />
    );
  }

  const workers = SCENARIO_WORKERS;

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-[var(--color-text-primary)]">
          Worker Fleet (Synthetic Demo Scope)
        </h1>
        <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
          Worker boot-sessions and observed heartbeat freshness. Liveness and durable lifecycle are rendered independently.
        </p>
      </div>

      <div className="border-y border-[var(--color-border-subtle)] overflow-hidden">
        <table className="relay-table">
          <thead>
            <tr>
              <th scope="col">Session ID</th>
              <th scope="col">Display Name</th>
              <th scope="col">Lifecycle State</th>
              <th scope="col">Observed Liveness</th>
              <th scope="col">Last Contact</th>
              <th scope="col">Active Assignment</th>
            </tr>
          </thead>
          <tbody>
            {workers.map((w) => (
              <tr key={w.session_id}>
                {/* Session ID */}
                <td className="font-mono text-xs">
                  <CopyField value={w.session_id} label="Worker Session ID" shorten truncateLength={6} />
                </td>

                {/* Display Name */}
                <td className="text-xs font-mono text-[var(--color-text-primary)]">
                  {w.display_name}
                </td>

                {/* Lifecycle State */}
                <td>
                  <span className={`badge ${w.state === 'STOPPED' ? 'badge-neutral' : w.state === 'DRAINING' ? 'badge-attention' : 'badge-neutral'}`}>
                    <span>{w.state}</span>
                  </span>
                </td>

                {/* Observed Liveness */}
                <td>
                  <ObservationBadge liveness={w.liveness} />
                </td>

                {/* Last Contact */}
                <td className="font-mono text-xs text-[var(--color-text-secondary)]">
                  {new Date(w.last_seen_at).toISOString().slice(11, 19)}Z
                </td>

                {/* Active Assignment */}
                <td className="font-mono text-xs">
                  {w.current_attempt_id ? (
                    <div className="flex items-center gap-1.5">
                      <span className="text-[var(--color-text-primary)] font-semibold">
                        Partition {w.current_partition_ordinal}
                      </span>
                      <span className="text-[var(--color-text-muted)]">
                        (<CopyField value={w.current_attempt_id} label="Attempt ID" shorten truncateLength={4} />)
                      </span>
                    </div>
                  ) : (
                    <span className="text-[var(--color-text-muted)]">None</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
