import React from 'react';
import { JobSummary } from '../../types/domain';
import { useRelay } from '../../context/RelayContext';
import { CopyField } from '../common/CopyField';
import { CapabilityUnavailable } from '../common/CapabilityUnavailable';
import { FileCode2 } from 'lucide-react';

interface DefinitionTabProps {
  job: JobSummary;
}

export const DefinitionTab: React.FC<DefinitionTabProps> = ({ job }) => {
  const { isSynthetic } = useRelay();
  const isSyntheticFixtureWithWorkload = isSynthetic && Boolean(job.workload_name);

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

      {/* Structured Fields Actually Exposed by Baseline Job Read */}
      <div className="py-4 border-b border-[var(--color-border-subtle)]">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-secondary)]">
            {isSyntheticFixtureWithWorkload ? 'Core Workload & Policy Parameters' : 'Baseline Job Identity & Lifecycle Parameters'}
          </h3>
          {isSyntheticFixtureWithWorkload && (
            <span className="badge badge-neutral text-[10px] font-mono">
              Synthetic Fixture Definition
            </span>
          )}
        </div>

        <dl className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 font-mono text-xs">
          <div>
            <dt className="text-[var(--color-text-muted)]">Definition Hash</dt>
            <dd className="mt-1">
              <CopyField value={job.definition_hash} label="Definition Hash" shorten truncateLength={8} />
            </dd>
          </div>

          <div>
            <dt className="text-[var(--color-text-muted)]">Partition Count</dt>
            <dd className="mt-1 text-[var(--color-text-primary)] font-semibold">
              {job.partition_count}
            </dd>
          </div>

          <div>
            <dt className="text-[var(--color-text-muted)]">Created At</dt>
            <dd className="mt-1 text-[var(--color-text-primary)]">
              {job.created_at ? `${new Date(job.created_at).toISOString().replace('T', ' ').slice(0, 19)} UTC` : '—'}
            </dd>
          </div>

          {isSyntheticFixtureWithWorkload ? (
            <>
              <div>
                <dt className="text-[var(--color-text-muted)]">Workload Name</dt>
                <dd className="mt-1 text-[var(--color-text-primary)] font-semibold">
                  {job.workload_name}
                </dd>
              </div>

              <div>
                <dt className="text-[var(--color-text-muted)]">Workload Version</dt>
                <dd className="mt-1 text-[var(--color-text-primary)]">
                  {job.workload_version}
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
            </>
          ) : (
            <>
              <div>
                <dt className="text-[var(--color-text-muted)]">Started At</dt>
                <dd className="mt-1 text-[var(--color-text-primary)]">
                  {job.started_at ? `${new Date(job.started_at).toISOString().replace('T', ' ').slice(0, 19)} UTC` : '—'}
                </dd>
              </div>

              <div>
                <dt className="text-[var(--color-text-muted)]">Finished At</dt>
                <dd className="mt-1 text-[var(--color-text-primary)]">
                  {job.finished_at ? `${new Date(job.finished_at).toISOString().replace('T', ' ').slice(0, 19)} UTC` : '—'}
                </dd>
              </div>

              <div>
                <dt className="text-[var(--color-text-muted)]">Job Status</dt>
                <dd className="mt-1 text-[var(--color-text-primary)] font-semibold">
                  {job.status}
                </dd>
              </div>
            </>
          )}
        </dl>
      </div>

      {/* In live mode: render BV09 capability gap for unexposed definition details. Do not fabricate raw submission descriptor! */}
      {!isSyntheticFixtureWithWorkload ? (
        <CapabilityUnavailable
          title="BACKEND READ AVAILABLE (BV09) — BROWSER LIVE SESSION INTEGRATION PENDING"
          description="The R1 backend implements detailed submission descriptor reads (BV09). However, consuming them in the browser requires the pending BV10 authentication adapter."
          requiredReadContract="GET /v1/jobs/{id}/definition"
        />
      ) : (
        /* Synthetic Mode: Structured JSON clearly labeled as fixture */
        <div className="py-4 border-b border-[var(--color-border-subtle)]">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-secondary)]">
              Synthetic Fixture Submission Descriptor
            </h3>
            <span className="badge badge-neutral text-[10px] font-mono">
              Fixture Data
            </span>
          </div>
          <pre className="p-3 rounded bg-[var(--color-surface-1)] text-xs font-mono text-[var(--color-text-secondary)] overflow-x-auto border-l-2 border-l-[var(--color-execution)]">
            {JSON.stringify({
              id: job.id,
              definition_hash: job.definition_hash,
              workload: {
                name: job.workload_name,
                version: job.workload_version
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
      )}
    </div>
  );
};
