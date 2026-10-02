import React, { useState } from 'react';
import { CopyField } from '../components/common/CopyField';
import { FlaskConical, CheckCircle2, GitCommit } from 'lucide-react';

export const FailureLabView: React.FC = () => {
  const [selectedStep, setSelectedStep] = useState<number>(4);

  const scenario = {
    title: 'Generation 4 Stale Completion After Generation 5 Acceptance',
    invariant: 'INVARIANT-PUBLICATION-01: An attempt cannot publish if superseded by a newer generation or already accepted result.',
    mode: 'RECORDED EVIDENCE',
    repoSha: 'bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc',
    testRef: 'tests/faults/test_process_faults.py::test_stale_generation_rejection',
    status: 'PASSED',
    expected: 'Generation 5 succeeds and publishes result. Generation 4 resumes after delay, uploads artifact, and attempts publication. Publication must be rejected with code stale_generation. Partition state remains SUCCEEDED and authoritative artifact remains Generation 5.',
    observed: 'Generation 5 published at 01:52:12Z. Generation 4 publication rejected with stale_generation at 01:53:00Z. Accepted result relation retained Generation 5 artifact. Zero state corruption.',
    steps: [
      { step: 1, time: '01:45:00Z', source: 'harness', actor: 'worker-1', action: 'Claimed Partition 0 (Generation 4)' },
      { step: 2, time: '01:45:30Z', source: 'runtime', actor: 'recovery-service', action: 'Lease expired; attempt transitioned to EXPIRED' },
      { step: 3, time: '01:50:00Z', source: 'harness', actor: 'worker-2', action: 'Claimed Partition 0 (Generation 5)' },
      { step: 4, time: '01:52:12Z', source: 'runtime', actor: 'publication-service', action: 'RESULT_ACCEPTED committed for Generation 5' },
      { step: 5, time: '01:53:00Z', source: 'runtime', actor: 'publication-service', action: 'PUBLICATION_REJECTED committed for Generation 4 (stale_generation)' },
    ]
  };

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      {/* Header */}
      <div className="p-4 rounded-lg bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)] space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <FlaskConical size={18} className="text-[var(--color-execution)]" aria-hidden="true" />
            <span className="font-semibold text-sm text-[var(--color-text-primary)]">
              {scenario.title}
            </span>
          </div>

          <div className="flex items-center gap-2 font-mono text-xs">
            <span className="px-2 py-0.5 rounded bg-[rgba(134,183,255,0.15)] text-[var(--color-execution)] border border-[rgba(134,183,255,0.3)] font-semibold tracking-wider">
              {scenario.mode}
            </span>
            <span className="badge badge-accepted">
              <CheckCircle2 size={12} aria-hidden="true" />
              <span>{scenario.status}</span>
            </span>
          </div>
        </div>

        <div className="text-xs font-mono text-[var(--color-text-secondary)]">
          <span className="text-[var(--color-text-muted)]">Invariant:</span> {scenario.invariant}
        </div>

        <div className="flex flex-wrap items-center gap-4 text-xs font-mono text-[var(--color-text-muted)] pt-2 border-t border-[var(--color-border-subtle)]">
          <div className="flex items-center gap-1.5">
            <GitCommit size={13} aria-hidden="true" />
            <span>Target SHA:</span>
            <CopyField value={scenario.repoSha} label="Repo SHA" shorten truncateLength={7} />
          </div>

          <div>
            <span>Evidence Ref:</span>{' '}
            <span className="text-[var(--color-text-secondary)]">{scenario.testRef}</span>
          </div>
        </div>
      </div>

      {/* Expected vs Observed Verdict */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="p-4 rounded-lg bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)]">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2">
            Expected Protocol Invariant
          </h2>
          <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
            {scenario.expected}
          </p>
        </div>

        <div className="p-4 rounded-lg bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)] authority-rail-accepted">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-accepted)] mb-2">
            Observed Authoritative Verdict
          </h2>
          <p className="text-xs text-[var(--color-text-primary)] leading-relaxed">
            {scenario.observed}
          </p>
        </div>
      </div>

      {/* Action and Durable Event Ledger */}
      <div className="p-4 rounded-lg bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)] space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-secondary)]">
            Correlated Action and Event Ledger
          </h2>
          <span className="text-xs font-mono text-[var(--color-text-muted)]">
            Ordered sequence of fault execution
          </span>
        </div>

        <div className="space-y-2">
          {scenario.steps.map((st) => {
            const isSelected = selectedStep === st.step;
            return (
              <div
                key={st.step}
                onClick={() => setSelectedStep(st.step)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setSelectedStep(st.step);
                  }
                }}
                tabIndex={0}
                role="button"
                aria-pressed={isSelected}
                className={`p-3 rounded-lg border text-xs font-mono transition-colors cursor-pointer flex flex-wrap items-center justify-between gap-3 ${
                  isSelected 
                    ? 'bg-[var(--color-surface-2)] border-[var(--color-execution)]' 
                    : 'bg-[var(--color-surface-1)] border-[var(--color-border-subtle)] hover:bg-[var(--color-surface-hover)]'
                }`}
              >
                <div className="flex items-center gap-3">
                  <span className="font-bold text-[var(--color-text-primary)]">
                    Step {st.step}
                  </span>
                  <span className={`px-1.5 py-0.5 rounded text-[11px] ${
                    st.source === 'runtime' 
                      ? 'bg-[rgba(121,217,170,0.1)] text-[var(--color-accepted)] border border-[rgba(121,217,170,0.2)]' 
                      : 'bg-[rgba(134,183,255,0.1)] text-[var(--color-execution)] border border-[rgba(134,183,255,0.2)]'
                  }`}>
                    {st.source}
                  </span>
                  <span className="text-[var(--color-text-primary)]">
                    {st.action}
                  </span>
                </div>

                <div className="flex items-center gap-4 text-[11px] text-[var(--color-text-muted)]">
                  <span>Actor: {st.actor}</span>
                  <span>{st.time}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
