import React, { useState } from 'react';
import { CopyField } from '../components/common/CopyField';
import { FlaskConical, CheckCircle2, GitCommit } from 'lucide-react';

export const FailureLabView: React.FC = () => {
  const [selectedStep, setSelectedStep] = useState<number>(4);

  const scenario = {
    title: 'Generation 4 Stale Completion After Generation 5 Acceptance (T04 Proof)',
    invariant: 'INVARIANT-PUBLICATION-01: An attempt cannot publish if superseded by a newer generation or already accepted result.',
    mode: 'RECORDED EVIDENCE',
    repoSha: 'bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc',
    testRef: 'tests/faults/test_process_faults.py::test_t04_exact_ordinal17_generations_1_through_5_real_stale_worker',
    jobId: 'bd750767-4348-452c-bf55-e441d6c2480e',
    partitionOrdinal: 17,
    partitionId: '7668f507-9cbe-4b99-9577-73b0c0d1703f',
    status: 'PASSED',
    expected: 'Generation 5 succeeds and publishes result. Generation 4 resumes after delay, uploads artifact, and attempts publication. Publication must be rejected with code stale_generation. Partition state remains SUCCEEDED and authoritative artifact remains Generation 5.',
    observed: 'Actual M3 T04 recorded run: Generation 4 attempt cbd5e956-6fc2-4f9b-ad9a-7c84b2567751 settled EXPIRED at 10:55:12Z. Artifact A d7e3a285-17c3-42f3-ae6d-276e5a86b2dd verified at 10:55:06Z. Generation 5 attempt 137858b2-0860-48b5-ba5c-3a6864c3de48 published artifact B 9f2c8e42-7cc8-475f-8f76-33f3885b6979 at 10:55:15Z. Worker A woke and sent completion request 1782c248-044e-4b47-9d01-ef8db4d496a3, rejected with HTTP 409 stale_generation.',
    steps: [
      { step: 1, time: '10:55:04Z', source: 'harness', actor: 'worker-A (PID 20580)', action: 'Claimed Partition 17 (Generation 4, attempt cbd5e956…)' },
      { step: 2, time: '10:55:06Z', source: 'worker', actor: 'worker-A (PID 20580)', action: 'Uploaded and verified Artifact A (d7e3a285…); paused before publication' },
      { step: 3, time: '10:55:12Z', source: 'runtime', actor: 'recovery-service (PID 26364)', action: 'Lease expired at 10:55:10Z; committed EXPIRED with 8s backoff' },
      { step: 4, time: '10:55:15Z', source: 'runtime', actor: 'worker-B (session 14bf7fe5…)', action: 'Claimed G5 (attempt 137858b2…); RESULT_ACCEPTED committed for Artifact B (9f2c8e42…)' },
      { step: 5, time: '10:55:20Z', source: 'runtime', actor: 'publication-service', action: 'Worker A completion request 1782c248… rejected with HTTP 409 stale_generation; PUBLICATION_REJECTED event recorded' },
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
            <span>Job:</span>{' '}
            <CopyField value={scenario.jobId} label="Job ID" shorten truncateLength={8} />
          </div>

          <div>
            <span>Target:</span>{' '}
            <span className="text-[var(--color-text-secondary)]">Partition {scenario.partitionOrdinal}</span>
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
