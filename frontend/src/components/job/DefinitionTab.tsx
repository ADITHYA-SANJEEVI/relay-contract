import React from 'react';
import { JobSummary } from '../../types/domain';
import { CopyField } from '../common/CopyField';
import { FileCode2 } from 'lucide-react';

interface DefinitionTabProps {
  job: JobSummary;
}

export const DefinitionTab: React.FC<DefinitionTabProps> = ({ job }) => {
  return (
    <div className="space-y-4" role="region" aria-label="Job definition and parameters">
      {/* Immutability Notice */}
      <div className="p-3 rounded-lg bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)] flex items-start gap-2.5 text-xs text-[var(--color-text-secondary)]">
        <FileCode2 size={16} className="text-[var(--color-execution)] flex-shrink-0 mt-0.5" aria-hidden="true" />
        <div>
          <span className="font-semibold text-[var(--color-text-primary)]">
            Immutable Job Definition:
          </span>{' '}
          Job definitions, partition allocations, and workload policies are frozen at submission and content-addressed by SHA-256 hash. They cannot be modified in-flight.
        </div>
      </div>

      {/* Structured Fields */}
      <div className="p-4 rounded-lg bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)]">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-secondary)] mb-3">
          Core Workload & Policy Parameters
        </h3>

        <dl className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 font-mono text-xs">
          <div>
            <dt className="text-[var(--color-text-muted)]">Definition Hash</dt>
            <dd className="mt-1">
              <CopyField value={job.definition_hash} label="Definition Hash" shorten truncateLength={8} />
            </dd>
          </div>

          <div>
            <dt className="text-[var(--color-text-muted)]">Workload Name</dt>
            <dd className="mt-1 text-[var(--color-text-primary)] font-semibold">
              {job.workload_name || 'normalize_aggregate'}
            </dd>
          </div>

          <div>
            <dt className="text-[var(--color-text-muted)]">Workload Version</dt>
            <dd className="mt-1 text-[var(--color-text-primary)]">
              {job.workload_version || '1'}
            </dd>
          </div>

          <div>
            <dt className="text-[var(--color-text-muted)]">Partition Count</dt>
            <dd className="mt-1 text-[var(--color-text-primary)] font-semibold">
              {job.partition_count}
            </dd>
          </div>

          <div>
            <dt className="text-[var(--color-text-muted)]">Default Max Attempts</dt>
            <dd className="mt-1 text-[var(--color-text-primary)]">
              5
            </dd>
          </div>

          <div>
            <dt className="text-[var(--color-text-muted)]">Default Lease Seconds</dt>
            <dd className="mt-1 text-[var(--color-text-primary)]">
              30s
            </dd>
          </div>
        </dl>
      </div>

      {/* Structured JSON */}
      <div className="p-4 rounded-lg bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)]">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-secondary)] mb-2">
          Committed Raw Submission Descriptor
        </h3>
        <pre className="p-3 rounded bg-[var(--color-canvas)] text-xs font-mono text-[var(--color-text-secondary)] overflow-x-auto border border-[var(--color-border-subtle)]">
          {JSON.stringify({
            id: job.id,
            definition_hash: job.definition_hash,
            workload: {
              name: job.workload_name || 'normalize_aggregate',
              version: job.workload_version || '1'
            },
            partition_count: job.partition_count,
            created_at: job.created_at,
            policy: {
              max_attempts: 5,
              lease_seconds: 30,
              max_attempt_seconds: 600
            }
          }, null, 2)}
        </pre>
      </div>
    </div>
  );
};
