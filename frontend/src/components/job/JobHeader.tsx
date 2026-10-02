import React from 'react';
import { JobSummary } from '../../types/domain';
import { RecordedStatusBadge } from '../common/StatusBadges';
import { CopyField } from '../common/CopyField';
import { RefreshCw, FileText } from 'lucide-react';

interface JobHeaderProps {
  job: JobSummary;
  onRefresh: () => void;
  isRefreshing?: boolean;
}

export const JobHeader: React.FC<JobHeaderProps> = ({ job, onRefresh, isRefreshing = false }) => {
  const hasPartialAccepted = parseInt(job.partial_result_count, 10) > 0;
  const hasFailedPartitions = parseInt(job.partition_counts.FAILED || '0', 10) > 0;

  let outcomeNote: string | null = null;
  if (job.status === 'FAILED' && hasPartialAccepted) {
    outcomeNote = 'Job failed · partial accepted results retained';
  } else if (job.status === 'RUNNING' && hasFailedPartitions) {
    outcomeNote = 'Work continues; failed partitions will make final outcome FAILED';
  }

  return (
    <div className="bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)] rounded-lg p-4 md:p-5">
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        {/* Identity & Status */}
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="text-xs text-[var(--color-text-muted)] uppercase tracking-wider font-mono">
              Job ID
            </span>
            <CopyField value={job.id} label="Job ID" className="text-base font-semibold text-[var(--color-text-primary)]" />
            <RecordedStatusBadge status={job.status} type="job" />
          </div>

          {outcomeNote && (
            <div className="text-xs font-medium text-[var(--color-attention)]">
              {outcomeNote}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-4 text-xs text-[var(--color-text-secondary)] font-mono">
            <div className="flex items-center gap-1.5">
              <FileText size={13} className="text-[var(--color-text-muted)]" aria-hidden="true" />
              <span>Definition Hash:</span>
              <CopyField value={job.definition_hash} label="Definition Hash" shorten truncateLength={8} />
            </div>

            {job.workload_name && (
              <div>
                <span>Workload:</span>{' '}
                <span className="text-[var(--color-text-primary)]">
                  {job.workload_name}:{job.workload_version || '1'}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2 self-start lg:self-center">
          <button
            type="button"
            onClick={onRefresh}
            disabled={isRefreshing}
            className="btn-secondary text-xs"
            aria-label="Refresh job snapshot"
          >
            <RefreshCw size={13} className={isRefreshing ? 'animate-spin' : ''} aria-hidden="true" />
            <span>{isRefreshing ? 'Refreshing…' : 'Refresh Snapshot'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
