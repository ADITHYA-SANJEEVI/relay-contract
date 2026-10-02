import React from 'react';
import { CopyField } from '../components/common/CopyField';
import { CheckCircle2 } from 'lucide-react';

export const EvidenceView: React.FC = () => {
  const reports = [
    {
      id: 'EV-M3-01',
      title: 'M3 Recovery, Bounded Retries & Generation Fencing Validation',
      kind: 'Validation Manifest',
      sha: 'bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc',
      recordedAt: '2026-10-02T16:03:00Z',
      verdict: 'PASS',
      itemsCount: 250,
      path: 'docs/M3_EVIDENCE.md'
    },
    {
      id: 'EV-M2-01',
      title: 'M2 Concurrent Ownership & Supervised Lease Renewal Validation',
      kind: 'Validation Manifest',
      sha: 'd2cf86ab44c3e1a034279c8873e3ff0517aa9831',
      recordedAt: '2026-10-02T04:00:00Z',
      verdict: 'PASS',
      itemsCount: 184,
      path: 'docs/M2_EVIDENCE.md'
    }
  ];

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-[var(--color-text-primary)]">
          Repository-Recorded Validation Evidence
        </h1>
        <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
          Formal correctness manifests committed in repository history. Tests and benchmarks are distinguished and never conflated.
        </p>
      </div>

      <div className="bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)] rounded-lg overflow-hidden">
        <table className="relay-table">
          <thead>
            <tr>
              <th scope="col">Report ID</th>
              <th scope="col">Title & Description</th>
              <th scope="col">Kind</th>
              <th scope="col">Commit SHA</th>
              <th scope="col">Items</th>
              <th scope="col">Verdict</th>
            </tr>
          </thead>
          <tbody>
            {reports.map((rep) => (
              <tr key={rep.id}>
                <td className="font-mono text-xs font-semibold text-[var(--color-text-primary)]">
                  {rep.id}
                </td>
                <td className="text-xs">
                  <div className="font-medium text-[var(--color-text-primary)]">{rep.title}</div>
                  <div className="font-mono text-[11px] text-[var(--color-text-muted)] mt-0.5">{rep.path}</div>
                </td>
                <td>
                  <span className="badge badge-neutral">
                    {rep.kind}
                  </span>
                </td>
                <td className="font-mono text-xs">
                  <CopyField value={rep.sha} label="Commit SHA" shorten truncateLength={7} />
                </td>
                <td className="font-mono text-xs text-[var(--color-text-secondary)]">
                  {rep.itemsCount} checks
                </td>
                <td>
                  <span className="badge badge-accepted">
                    <CheckCircle2 size={12} aria-hidden="true" />
                    <span>{rep.verdict}</span>
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
