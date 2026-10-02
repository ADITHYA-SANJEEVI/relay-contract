import React, { useState } from 'react';
import { PartitionItem, GenerationDetail, AuthorityState, RelayEvent, CapabilityState } from '../../types/domain';
import { AuthorityPanel } from '../common/AuthorityPanel';
import { GenerationStack } from './GenerationStack';
import { RecordedStatusBadge, ObservationBadge } from '../common/StatusBadges';
import { CopyField } from '../common/CopyField';
import { X } from 'lucide-react';

interface PartitionInspectorProps {
  partition: PartitionItem;
  authority: AuthorityState | null;
  generations: GenerationDetail[];
  events: RelayEvent[];
  observedAt: string;
  onClose?: () => void;
  isLoading?: boolean;
  historyGap?: CapabilityState | null;
}

export const PartitionInspector: React.FC<PartitionInspectorProps> = ({
  partition,
  authority,
  generations,
  events,
  observedAt,
  onClose,
  isLoading = false,
  historyGap,
}) => {
  const [selectedGeneration, setSelectedGeneration] = useState<string | null>(
    generations.length > 0 ? generations[0].generation : null
  );

  const activeGenDetail = generations.find(g => g.generation === selectedGeneration);

  // Check deadline passed observation
  const now = new Date(observedAt).getTime();
  const leaseExpiry = partition.lease_expires_at ? new Date(partition.lease_expires_at).getTime() : null;
  const isDeadlinePassed = Boolean(
    partition.status === 'RUNNING' && 
    leaseExpiry && 
    now > leaseExpiry
  );

  // Correlated events for this partition
  const correlatedEvents = events.filter(e => e.partition_ordinal === partition.ordinal);

  return (
    <div 
      className="flex flex-col h-full bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)] rounded-lg overflow-hidden"
      role="region"
      aria-label={`Partition ${partition.ordinal} Inspector`}
    >
      {/* 1. Header & Identity */}
      <div className="p-4 border-b border-[var(--color-border-subtle)] flex items-center justify-between bg-[var(--color-surface-1)]">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-[var(--color-text-primary)]">
              Partition {partition.ordinal}
            </h2>
            <RecordedStatusBadge status={partition.status} type="partition" />
          </div>
          <div className="mt-1 text-xs text-[var(--color-text-muted)] font-mono">
            ID: <CopyField value={partition.id} label="Partition ID" shorten truncateLength={8} />
          </div>
        </div>

        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="btn-icon text-[var(--color-text-secondary)]"
            aria-label="Close partition inspector"
          >
            <X size={16} aria-hidden="true" />
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {/* 2. Persistent Anchored Authority Panel */}
        <div>
          <div className="text-label mb-2">Accepted Result Authority</div>
          <AuthorityPanel authority={authority} isLoading={isLoading} />
        </div>

        {/* 3. Current Generation & Ownership Observation */}
        <div className="p-3 rounded bg-[var(--color-surface-2)] border border-[var(--color-border-subtle)] space-y-2 text-xs">
          <div className="flex items-center justify-between font-mono">
            <span className="text-[var(--color-text-secondary)]">Current Generation:</span>
            <span className="font-semibold text-[var(--color-text-primary)]">G{partition.generation}</span>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-[var(--color-text-secondary)]">Ownership Observation:</span>
            <div>
              {isDeadlinePassed ? (
                <ObservationBadge isDeadlinePassed={true} attemptStatus="ACTIVE" />
              ) : partition.lease_expires_at ? (
                <span className="font-mono text-xs text-[var(--color-text-secondary)]">
                  Lease to {new Date(partition.lease_expires_at).toISOString().slice(11, 19)}Z
                </span>
              ) : (
                <span className="text-xs text-[var(--color-text-muted)]">No active lease</span>
              )}
            </div>
          </div>

          {partition.last_error_code && (
            <div className="flex items-center justify-between text-[var(--color-failure)] font-mono">
              <span>Last Error Code:</span>
              <span>{partition.last_error_code}</span>
            </div>
          )}
        </div>

        {/* 4. Generation Stack */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-label">Generation History</span>
            <span className="text-xs text-[var(--color-text-muted)] font-mono">
              {historyGap ? '(Gap BV03)' : `(${generations.length} recorded)`}
            </span>
          </div>
          <GenerationStack
            generations={generations}
            selectedGeneration={selectedGeneration}
            onSelectGeneration={(gen) => setSelectedGeneration(gen.generation)}
            isLoading={isLoading}
            isGap={Boolean(historyGap)}
            gapCapability={historyGap}
          />
        </div>

        {/* 5. Selected Generation Detail */}
        {activeGenDetail && (
          <div className="p-3.5 rounded-lg bg-[var(--color-surface-2)] border border-[var(--color-border-subtle)] space-y-2.5 text-xs">
            <div className="flex items-center justify-between pb-2 border-b border-[var(--color-border-subtle)]">
              <span className="font-semibold text-[var(--color-text-primary)] font-mono">
                Generation {activeGenDetail.generation} Detail
              </span>
              <RecordedStatusBadge status={activeGenDetail.status} type="attempt" />
            </div>

            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-2 font-mono text-[11px]">
              <div>
                <dt className="text-[var(--color-text-muted)]">Attempt ID</dt>
                <dd className="mt-0.5">
                  <CopyField value={activeGenDetail.attempt_id} label="Attempt ID" shorten truncateLength={6} />
                </dd>
              </div>

              <div>
                <dt className="text-[var(--color-text-muted)]">Worker Session</dt>
                <dd className="mt-0.5">
                  {activeGenDetail.worker_session_id ? (
                    <CopyField value={activeGenDetail.worker_session_id} label="Worker Session" shorten truncateLength={6} />
                  ) : (
                    <span className="text-[var(--color-text-muted)]">Unrecorded</span>
                  )}
                </dd>
              </div>

              <div>
                <dt className="text-[var(--color-text-muted)]">Claimed At</dt>
                <dd className="mt-0.5 text-[var(--color-text-primary)]">
                  {new Date(activeGenDetail.claimed_at).toISOString().slice(11, 19)}Z
                </dd>
              </div>

              <div>
                <dt className="text-[var(--color-text-muted)]">Last Renew Seq</dt>
                <dd className="mt-0.5 text-[var(--color-text-primary)]">
                  #{activeGenDetail.last_renew_seq}
                </dd>
              </div>
            </dl>
          </div>
        )}

        {/* 6. Correlated Event Slice */}
        <div>
          <div className="text-label mb-2">Partition Events ({correlatedEvents.length})</div>
          {correlatedEvents.length === 0 ? (
            <div className="p-3 rounded bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)] text-xs text-[var(--color-text-muted)] text-center">
              No correlated events found in loaded range for Partition {partition.ordinal}.
            </div>
          ) : (
            <div className="space-y-1.5 font-mono text-xs">
              {correlatedEvents.map(e => (
                <div key={e.seq} className="p-2 rounded bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)] flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[var(--color-text-muted)]">#{e.seq}</span>
                    <span className="text-[var(--color-text-primary)] font-semibold">{e.type}</span>
                  </div>
                  <span className="text-[var(--color-text-muted)] text-[11px]">
                    {new Date(e.occurred_at).toISOString().slice(11, 19)}Z
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
