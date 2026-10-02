import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRelay } from '../context/RelayContext';
import { JOB_ID_NORMAL, JOB_ID_FAILED_WITH_PARTIAL, JOB_ID_RUNNING_WITH_FAILURE } from '../fixtures/scenarios';
import { Search, AlertTriangle, Layers } from 'lucide-react';

export const OverviewView: React.FC = () => {
  const navigate = useNavigate();
  const { connectionStatus } = useRelay();
  const [jobInput, setJobInput] = useState('');
  const [inputError, setInputError] = useState<string | null>(null);

  const handleOpenJob = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = jobInput.trim();
    if (!trimmed) {
      setInputError('Please enter a valid UUID.');
      return;
    }
    // Basic UUID validation
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(trimmed)) {
      setInputError('Invalid UUID format. Relay job identities are standard 36-character UUIDs.');
      return;
    }
    setInputError(null);
    navigate(`/board/jobs/${trimmed}`);
  };

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Title & Introduction */}
      <div>
        <h1 className="text-xl font-semibold text-[var(--color-text-primary)]">
          Relay Execution Investigation Console
        </h1>
        <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
          Inspect distributed state transitions, generation fencing, artifact verification, and committed result authority.
        </p>
      </div>

      {/* Open Job by ID Card */}
      <div className="p-5 rounded-lg bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)]">
        <h2 className="text-sm font-semibold text-[var(--color-text-primary)] mb-1">
          Open Job Investigation
        </h2>
        <p className="text-xs text-[var(--color-text-secondary)] mb-3">
          Enter an exact Job UUID to inspect partition lifecycles, generation history, and accepted results.
        </p>

        <form onSubmit={handleOpenJob} className="flex flex-col sm:flex-row gap-2 max-w-2xl">
          <div className="flex-1 relative">
            <input
              type="text"
              value={jobInput}
              onChange={(e) => setJobInput(e.target.value)}
              placeholder="e.g. 11111111-1111-4111-8111-111111111111"
              className="w-full input-control font-mono text-xs pr-8"
              aria-label="Job UUID input"
            />
          </div>
          <button type="submit" className="btn-primary text-xs">
            <Search size={13} aria-hidden="true" />
            <span>Open Job</span>
          </button>
        </form>

        {inputError && (
          <p className="mt-2 text-xs text-[var(--color-failure)] font-mono" role="alert">
            {inputError}
          </p>
        )}

        {/* Demo Quick-links */}
        <div className="mt-4 pt-3 border-t border-[var(--color-border-subtle)] text-xs text-[var(--color-text-secondary)]">
          <span className="text-[var(--color-text-muted)]">Available Showcase Jobs:</span>
          <div className="mt-1.5 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => navigate(`/board/jobs/${JOB_ID_NORMAL}`)}
              className="btn-secondary text-[11px] font-mono py-1 px-2.5 h-auto"
            >
              Standard Showcase (Scenario A/B) →
            </button>
            <button
              type="button"
              onClick={() => navigate(`/board/jobs/${JOB_ID_RUNNING_WITH_FAILURE}`)}
              className="btn-secondary text-[11px] font-mono py-1 px-2.5 h-auto"
            >
              Running with Failed Partition →
            </button>
            <button
              type="button"
              onClick={() => navigate(`/board/jobs/${JOB_ID_FAILED_WITH_PARTIAL}`)}
              className="btn-secondary text-[11px] font-mono py-1 px-2.5 h-auto"
            >
              Failed with Partial Accepted Output →
            </button>
          </div>
        </div>
      </div>

      {/* Needs Attention / Active Work Summary */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Active Attention Items */}
        <div className="p-4 rounded-lg bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)]">
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle size={15} className="text-[var(--color-attention)]" aria-hidden="true" />
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-primary)]">
              Needs Attention
            </h3>
          </div>

          <div className="space-y-2 text-xs">
            <div className="p-2.5 rounded bg-[rgba(240,198,116,0.08)] border border-[rgba(240,198,116,0.2)] flex items-start justify-between">
              <div>
                <div className="font-semibold text-[var(--color-attention)]">
                  Partition 1: Deadline Passed
                </div>
                <div className="text-[11px] text-[var(--color-text-secondary)] mt-0.5">
                  ACTIVE attempt lease elapsed; awaiting recovery service settlement.
                </div>
              </div>
              <button
                type="button"
                onClick={() => navigate(`/board/jobs/${JOB_ID_NORMAL}?partition=1`)}
                className="text-[var(--color-execution)] text-[11px] hover:underline"
              >
                Inspect
              </button>
            </div>

            <div className="p-2.5 rounded bg-[rgba(255,146,155,0.08)] border border-[rgba(255,146,155,0.2)] flex items-start justify-between">
              <div>
                <div className="font-semibold text-[var(--color-failure)]">
                  Partition 3: Terminal Failure
                </div>
                <div className="text-[11px] text-[var(--color-text-secondary)] mt-0.5">
                  Worker crashed; job continues draining remaining partitions.
                </div>
              </div>
              <button
                type="button"
                onClick={() => navigate(`/board/jobs/${JOB_ID_RUNNING_WITH_FAILURE}?partition=3`)}
                className="text-[var(--color-execution)] text-[11px] hover:underline"
              >
                Inspect
              </button>
            </div>
          </div>
        </div>

        {/* Global Cluster Capability Note */}
        <div className="p-4 rounded-lg bg-[var(--color-surface-1)] border border-[var(--color-border-subtle)]">
          <div className="flex items-center gap-2 mb-3">
            <Layers size={15} className="text-[var(--color-execution)]" aria-hidden="true" />
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-primary)]">
              Installation Scope
            </h3>
          </div>

          <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
            In accordance with Relay's distributed authority model, the Control Board does not poll global aggregate counters or present fabricated installation-wide uptime metrics.
          </p>

          <dl className="mt-3 space-y-1.5 text-xs font-mono">
            <div className="flex items-center justify-between">
              <dt className="text-[var(--color-text-muted)]">API Process:</dt>
              <dd className={connectionStatus.apiReachable ? 'text-[var(--color-accepted)]' : 'text-[var(--color-failure)]'}>
                {connectionStatus.apiReachable ? 'Reachable' : 'Unreachable'}
              </dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-[var(--color-text-muted)]">Database Revision:</dt>
              <dd className="text-[var(--color-text-primary)]">
                {connectionStatus.dbRevision || '0002_readiness'}
              </dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-[var(--color-text-muted)]">Catalogue Route:</dt>
              <dd className="text-[var(--color-attention)]">
                BV01 Gap (Planned)
              </dd>
            </div>
          </dl>
        </div>
      </div>
    </div>
  );
};
