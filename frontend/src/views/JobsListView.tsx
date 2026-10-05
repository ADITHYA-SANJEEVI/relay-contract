import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useRelay } from '../context/RelayContext';
import { 
  SCENARIO_NORMAL_JOB, 
  SCENARIO_C_JOB, 
  SCENARIO_D_JOB 
} from '../fixtures/scenarios';
import { RecordedStatusBadge } from '../components/common/StatusBadges';
import { CopyField } from '../components/common/CopyField';
import { CapabilityUnavailable } from '../components/common/CapabilityUnavailable';
import { ArrowRight } from 'lucide-react';

export const JobsListView: React.FC = () => {
  const navigate = useNavigate();
  const { isSynthetic, liveAdapter } = useRelay();

  if (!isSynthetic) {
    const gap = liveAdapter.getJobsCatalogueGap();
    return (
      <CapabilityUnavailable
        capability={gap}
        type="gap"
      />
    );
  }

  const jobs = [SCENARIO_NORMAL_JOB, SCENARIO_C_JOB, SCENARIO_D_JOB];

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-[var(--color-text-primary)]">
            Jobs Catalogue (Synthetic Demo Scope)
          </h1>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
            Deterministic execution scenarios loaded in fixture mode.
          </p>
        </div>
      </div>

      <div className="border-y border-[var(--color-border-subtle)] overflow-hidden">
        <table className="relay-table">
          <thead>
            <tr>
              <th scope="col">Job ID</th>
              <th scope="col">Status</th>
              <th scope="col">Workload</th>
              <th scope="col">Accepted / Total</th>
              <th scope="col">Created At</th>
              <th scope="col" className="text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr 
                key={job.id}
                className="cursor-pointer"
                onClick={() => navigate(`/board/jobs/${job.id}`)}
              >
                <td className="font-mono text-xs">
                  <CopyField value={job.id} label="Job ID" shorten truncateLength={8} />
                </td>
                <td>
                  <RecordedStatusBadge status={job.status} type="job" />
                </td>
                <td className="font-mono text-xs text-[var(--color-text-secondary)]">
                  {job.workload_name}:{job.workload_version}
                </td>
                <td className="font-mono text-xs font-semibold text-[var(--color-accepted)]">
                  {job.partial_result_count} / {job.partition_count}
                </td>
                <td className="font-mono text-xs text-[var(--color-text-muted)]">
                  {new Date(job.created_at).toISOString().slice(0, 19).replace('T', ' ')}Z
                </td>
                <td className="text-right">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      navigate(`/board/jobs/${job.id}`);
                    }}
                    className="btn-secondary text-xs py-1 px-2.5 h-auto inline-flex items-center gap-1"
                  >
                    <span>Inspect</span>
                    <ArrowRight size={12} aria-hidden="true" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
