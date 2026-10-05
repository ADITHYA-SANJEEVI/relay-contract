import React from 'react';
import { JobSummary } from '../../types/domain';

interface JobSummaryStripProps {
  job: JobSummary;
  observedAt: string;
}

export const JobSummaryStrip: React.FC<JobSummaryStripProps> = ({ job, observedAt }) => {
  const partial = parseInt(job.partial_result_count, 10);
  const total = parseInt(job.partition_count, 10);
  const percent = total > 0 ? Math.round((partial / total) * 100) : 0;

  // Elapsed computation
  const createdAt = new Date(job.created_at).getTime();
  const endTime = job.finished_at ? new Date(job.finished_at).getTime() : new Date(observedAt).getTime();
  const elapsedSecs = Math.max(0, Math.floor((endTime - createdAt) / 1000));
  const mins = Math.floor(elapsedSecs / 60);
  const secs = elapsedSecs % 60;
  const elapsedStr = `${mins}m ${secs}s${job.finished_at ? '' : ' (active)'}`;

  return (
    <div 
      className="pb-2 flex flex-wrap items-center justify-between gap-y-3 gap-x-6 min-h-[52px]"
      role="region"
      aria-label="Job execution summary"
    >
      {/* Acceptance Progress */}
      <div className="flex flex-col min-w-[180px]">
        <div className="flex items-center justify-between text-xs mb-1">
          <span className="text-[var(--color-text-secondary)] font-medium">Accepted Progress</span>
          <span className="font-mono font-semibold text-[var(--color-accepted)]">
            {job.partial_result_count} / {job.partition_count} ({percent}%)
          </span>
        </div>
        <div className="w-full bg-[var(--color-surface-2)] h-2 rounded-full overflow-hidden border border-[var(--color-border-subtle)]">
          <div 
            className="h-full bg-[var(--color-accepted)] transition-all duration-300"
            style={{ width: `${percent}%` }}
            role="progressbar"
            aria-valuenow={partial}
            aria-valuemin={0}
            aria-valuemax={total}
            aria-label="Accepted partitions progress"
          />
        </div>
      </div>

      {/* Partition State Breakdown */}
      <div className="flex items-center gap-3 text-xs font-mono">
        <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-[rgba(121,217,170,0.1)] border border-[rgba(121,217,170,0.2)]">
          <span className="text-[var(--color-text-secondary)] text-[11px]">SUCCEEDED:</span>
          <span className="font-semibold text-[var(--color-accepted)]">{job.partition_counts.SUCCEEDED || '0'}</span>
        </div>

        <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-[rgba(134,183,255,0.1)] border border-[rgba(134,183,255,0.2)]">
          <span className="text-[var(--color-text-secondary)] text-[11px]">RUNNING:</span>
          <span className="font-semibold text-[var(--color-execution)]">{job.partition_counts.RUNNING || '0'}</span>
        </div>

        <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-[rgba(139,158,180,0.1)] border border-[var(--color-border-subtle)]">
          <span className="text-[var(--color-text-secondary)] text-[11px]">READY:</span>
          <span className="font-semibold text-[var(--color-text-primary)]">{job.partition_counts.READY || '0'}</span>
        </div>

        <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-[rgba(255,146,155,0.1)] border border-[rgba(255,146,155,0.2)]">
          <span className="text-[var(--color-text-secondary)] text-[11px]">FAILED:</span>
          <span className="font-semibold text-[var(--color-failure)]">{job.partition_counts.FAILED || '0'}</span>
        </div>
      </div>

      {/* Attempts & Timing */}
      <div className="flex items-center gap-5 text-xs text-[var(--color-text-secondary)] font-mono ml-auto">
        <div>
          <span className="text-[var(--color-text-muted)]">Attempts:</span>{' '}
          <span className="text-[var(--color-text-primary)] font-semibold">{job.attempt_count}</span>
        </div>

        <div>
          <span className="text-[var(--color-text-muted)]">Elapsed:</span>{' '}
          <span className="text-[var(--color-text-primary)] font-semibold">{elapsedStr}</span>
        </div>

        <div>
          <span className="text-[var(--color-text-muted)]">Observed:</span>{' '}
          <span className="text-[var(--color-text-primary)]">
            {new Date(observedAt).toISOString().slice(11, 19)}Z
          </span>
        </div>
      </div>
    </div>
  );
};
