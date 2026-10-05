import React, { useState } from 'react';
import { JobSummary } from '../../types/domain';
import { useRelay } from '../../context/RelayContext';
import { CopyField } from '../common/CopyField';
import { Download, AlertTriangle, ShieldCheck } from 'lucide-react';

interface ResultsTabProps {
  job: JobSummary;
}

export const ResultsTab: React.FC<ResultsTabProps> = ({ job }) => {
  const { isSynthetic, liveAdapter } = useRelay();
  const [resultsLoaded, setResultsLoaded] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  const isComplete = job.complete && job.status === 'SUCCEEDED';
  const partialCount = parseInt(job.partial_result_count, 10);

  const handleLoadResults = async () => {
    setIsLoading(true);
    setError(null);
    try {
      if (isSynthetic) {
        // Return synthetic verified accepted manifests
        setResults([
          {
            ordinal: 0,
            artifact_id: 'bbbbbbbb-5555-4555-8555-555555555555',
            generation: '5',
            sha256: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
            object_version: 'v2.5.final-g5',
            size_bytes: '1048576',
            content_url: '/v1/artifacts/bbbbbbbb-5555-4555-8555-555555555555/content'
          }
        ]);
        setResultsLoaded(true);
      } else {
        const res = await liveAdapter.getResults(job.id);
        setResults(res.items);
        setResultsLoaded(true);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load accepted manifests');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="space-y-4" role="region" aria-label="Job accepted results">
      {/* Integrity work notice banner */}
      <div className="p-3 rounded-lg bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)] flex items-start gap-2.5 text-xs text-[var(--color-text-secondary)]">
        <ShieldCheck size={16} className="text-[var(--color-verified)] flex-shrink-0 mt-0.5" aria-hidden="true" />
        <div>
          <span className="font-semibold text-[var(--color-text-primary)]">
            Verified Result Manifest Policy:
          </span>{' '}
          Querying results executes an on-demand cryptographic verification of pinned bytes in object storage against the committed SHA-256 hash. This operation is explicit-only and never queried continuously by background polling.
        </div>
      </div>

      {/* Partial results warning if not complete */}
      {!isComplete && (
        <div className="p-3 rounded-lg bg-[rgba(240,198,116,0.1)] border border-[rgba(240,198,116,0.3)] flex items-center gap-2 text-xs text-[var(--color-attention)]">
          <AlertTriangle size={15} aria-hidden="true" />
          <span>
            {job.status === 'FAILED'
              ? `Job failed · Retaining ${partialCount} partial accepted output(s). Not a complete execution result.`
              : `Job in progress · ${partialCount} of ${job.partition_count} partitions currently accepted.`}
          </span>
        </div>
      )}

      {/* Load action button */}
      {!resultsLoaded ? (
        <div className="p-8 rounded-lg bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)] text-center space-y-3">
          <p className="text-xs text-[var(--color-text-secondary)] max-w-md mx-auto">
            {partialCount} accepted output(s) recorded in database. Click below to load and verify pinned manifests.
          </p>
          <button
            type="button"
            onClick={handleLoadResults}
            disabled={isLoading || partialCount === 0}
            className="btn-primary text-xs"
          >
            <Download size={13} aria-hidden="true" />
            <span>{isLoading ? 'Verifying manifests…' : 'Load Verified Accepted Manifests'}</span>
          </button>
        </div>
      ) : (
        <div className="border-y border-[var(--color-border-subtle)] overflow-hidden">
          <div className="p-3 border-b border-[var(--color-border-subtle)] flex items-center justify-between text-xs bg-[var(--color-canvas)]">
            <span className="font-semibold text-[var(--color-text-primary)]">
              Accepted Result Manifests ({results.length})
            </span>
            <span className="font-mono text-[var(--color-text-muted)] text-[11px]">
              All pinned hashes verified against storage
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="relay-table">
              <thead>
                <tr>
                  <th scope="col" className="w-24">Partition</th>
                  <th scope="col">Artifact ID</th>
                  <th scope="col" className="w-20">Gen</th>
                  <th scope="col">SHA-256</th>
                  <th scope="col">Object Version</th>
                  <th scope="col" className="text-right">Size</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr key={r.artifact_id} className="font-mono text-xs">
                    <td className="font-semibold text-[var(--color-text-primary)]">
                      Partition {r.ordinal}
                    </td>
                    <td>
                      <CopyField value={r.artifact_id} label="Artifact ID" shorten truncateLength={6} />
                    </td>
                    <td>G{r.generation}</td>
                    <td>
                      <CopyField value={r.sha256} label="SHA-256" shorten truncateLength={8} />
                    </td>
                    <td className="text-[var(--color-text-secondary)]">
                      {r.object_version}
                    </td>
                    <td className="text-right text-[var(--color-text-secondary)]">
                      {r.size_bytes} bytes
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {error && (
        <div className="p-3 rounded bg-[rgba(255,146,155,0.1)] border border-[var(--color-failure)] text-xs text-[var(--color-failure)]">
          {error}
        </div>
      )}
    </div>
  );
};
