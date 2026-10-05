import React from 'react';
import { PartitionItem } from '../../types/domain';
import { RecordedStatusBadge, ObservationBadge } from '../common/StatusBadges';
import { CopyField } from '../common/CopyField';
import { CheckCircle2, ChevronRight, AlertTriangle } from 'lucide-react';

interface PartitionTableProps {
  partitions: PartitionItem[];
  selectedPartitionId: string | null;
  onSelectPartition: (partition: PartitionItem) => void;
  statusFilter: string;
  onChangeStatusFilter: (status: string) => void;
  observedAt: string;
  isLoading?: boolean;
}

export const PartitionTable: React.FC<PartitionTableProps> = ({
  partitions,
  selectedPartitionId,
  onSelectPartition,
  statusFilter,
  onChangeStatusFilter,
  observedAt,
  isLoading = false,
}) => {
  const filterOptions = ['ALL', 'READY', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED'];

  return (
    <div className="flex flex-col h-full border-y xl:border border-[var(--color-border-subtle)] overflow-hidden">
      {/* Table Toolbar */}
      <div className="p-3 border-b border-[var(--color-border-subtle)] flex flex-wrap items-center justify-between gap-3 bg-[var(--color-surface-1)]">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-[var(--color-text-primary)]">
            Partitions
          </span>
          <span className="text-xs text-[var(--color-text-muted)] font-mono">
            ({partitions.length} loaded)
          </span>
        </div>

        {/* Filter */}
        <div className="flex items-center gap-1.5 text-xs">
          <label htmlFor="partition-status-filter" className="text-[var(--color-text-secondary)]">
            Status:
          </label>
          <select
            id="partition-status-filter"
            value={statusFilter}
            onChange={(e) => onChangeStatusFilter(e.target.value)}
            className="bg-[var(--color-surface-2)] text-[var(--color-text-primary)] border border-[var(--color-border-control)] text-xs rounded px-2 py-1 font-mono"
            aria-label="Filter partitions by status"
          >
            {filterOptions.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Semantic Table Container */}
      <div className="flex-1 overflow-x-auto overflow-y-auto" tabIndex={0} aria-label="Partition list table">
        <table className="relay-table">
          <thead>
            <tr>
              <th scope="col" className="w-24">Ordinal</th>
              <th scope="col" className="w-28">Status</th>
              <th scope="col" className="w-20">Gen</th>
              <th scope="col">Accepted Result</th>
              <th scope="col">Latest Attempt</th>
              <th scope="col">Lease / Deadline Observation</th>
              <th scope="col">Last Error</th>
              <th scope="col" className="w-16 text-right">Inspect</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && partitions.length === 0 ? (
              <tr>
                <td colSpan={8} className="text-center py-8 text-xs text-[var(--color-text-muted)]">
                  Loading partition records…
                </td>
              </tr>
            ) : partitions.length === 0 ? (
              <tr>
                <td colSpan={8} className="text-center py-8 text-xs text-[var(--color-text-muted)]">
                  No partitions match the selected filter.
                </td>
              </tr>
            ) : (
              partitions.map((partition) => {
                const isSelected = partition.id === selectedPartitionId;
                const hasAccepted = Boolean(partition.accepted_artifact_id);

                // Deadline observation check relative to observedAt
                const now = new Date(observedAt).getTime();
                const leaseExpiry = partition.lease_expires_at ? new Date(partition.lease_expires_at).getTime() : null;
                const isDeadlinePassed = Boolean(
                  partition.status === 'RUNNING' && 
                  leaseExpiry && 
                  now > leaseExpiry
                );

                return (
                  <tr
                    key={partition.id}
                    data-partition-ordinal={partition.ordinal}
                    onClick={() => onSelectPartition(partition)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        onSelectPartition(partition);
                      }
                    }}
                    tabIndex={0}
                    role="row"
                    aria-selected={isSelected}
                    className={`cursor-pointer transition-colors ${isSelected ? 'row-selected' : ''}`}
                  >
                    {/* Ordinal */}
                    <td className="font-mono font-medium text-[var(--color-text-primary)]">
                      Partition {partition.ordinal}
                    </td>

                    {/* Status */}
                    <td>
                      <RecordedStatusBadge status={partition.status} type="partition" />
                    </td>

                    {/* Generation */}
                    <td className="font-mono text-xs">
                      G{partition.generation}
                    </td>

                    {/* Accepted Authority */}
                    <td>
                      {hasAccepted ? (
                        <div className="flex items-center gap-1.5 text-xs text-[var(--color-accepted)] font-mono">
                          <CheckCircle2 size={13} aria-hidden="true" />
                          <span>Accepted</span>
                          {partition.accepted_generation && (
                            <span className="text-[var(--color-text-muted)]">
                              (G{partition.accepted_generation})
                            </span>
                          )}
                        </div>
                      ) : (
                        <span className="text-xs text-[var(--color-text-muted)]">
                          None accepted
                        </span>
                      )}
                    </td>

                    {/* Latest Attempt */}
                    <td className="font-mono text-xs">
                      {partition.attempt_id ? (
                        <CopyField value={partition.attempt_id} label="Attempt ID" shorten truncateLength={6} />
                      ) : (
                        <span className="text-[var(--color-text-muted)]">—</span>
                      )}
                    </td>

                    {/* Lease Observation */}
                    <td>
                      {isDeadlinePassed ? (
                        <ObservationBadge isDeadlinePassed={true} attemptStatus="ACTIVE" />
                      ) : partition.lease_expires_at ? (
                        <span className="font-mono text-xs text-[var(--color-text-secondary)]" title={`Lease: ${partition.lease_expires_at}`}>
                          Expires {new Date(partition.lease_expires_at).toISOString().slice(11, 19)}Z
                        </span>
                      ) : (
                        <span className="text-xs text-[var(--color-text-muted)]">—</span>
                      )}
                    </td>

                    {/* Last Error */}
                    <td>
                      {partition.last_error_code ? (
                        <span className="inline-flex items-center gap-1 font-mono text-xs text-[var(--color-failure)]">
                          <AlertTriangle size={12} aria-hidden="true" />
                          <span>{partition.last_error_code}</span>
                        </span>
                      ) : (
                        <span className="text-xs text-[var(--color-text-muted)]">—</span>
                      )}
                    </td>

                    {/* Inspect target */}
                    <td className="text-right">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectPartition(partition);
                        }}
                        className="btn-icon text-[var(--color-text-secondary)] hover:text-[var(--color-execution)]"
                        aria-label={`Inspect Partition ${partition.ordinal}`}
                      >
                        <ChevronRight size={15} aria-hidden="true" />
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
