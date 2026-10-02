import React, { useState } from 'react';
import { useRelay } from '../../context/RelayContext';
import { ScenarioKey } from '../../api/fixtureAdapter';
import { AlertTriangle, Lock, X, ShieldAlert, Sparkles } from 'lucide-react';

export const SyntheticBanner: React.FC = () => {
  const { isSynthetic, activeScenario, setScenario, setSyntheticMode, refreshHealth } = useRelay();
  const [showPrereqModal, setShowPrereqModal] = useState(false);

  const handleScenarioChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setScenario(e.target.value as ScenarioKey);
  };

  const handleConfirmLive = async () => {
    setShowPrereqModal(false);
    setSyntheticMode(false);
    await refreshHealth();
  };

  if (!isSynthetic) {
    return (
      <div
        className="px-4 py-1.5 bg-[rgba(240,198,116,0.12)] border-b border-[var(--color-attention)] text-xs text-[var(--color-attention)] flex flex-wrap items-center justify-between gap-2"
        role="banner"
        aria-label="Live unauthenticated cluster warning"
      >
        <div className="flex items-center gap-2 font-mono">
          <ShieldAlert size={14} className="flex-shrink-0" aria-hidden="true" />
          <span className="font-bold">LIVE CLUSTER MODE (UNAUTHENTICATED)</span>
          <span className="hidden md:inline text-[var(--color-text-secondary)]">
            — Baseline Relay requires BV10 browser auth adapter for operator reads. Authenticated job data unavailable.
          </span>
        </div>

        <button
          type="button"
          onClick={() => setSyntheticMode(true)}
          className="btn-secondary text-[11px] py-0.5 px-2 h-6 inline-flex items-center gap-1 font-mono text-[var(--color-text-primary)]"
          title="Return to synthetic deterministic proof scenarios"
        >
          <Sparkles size={11} aria-hidden="true" />
          <span>Switch to Synthetic Demo</span>
        </button>
      </div>
    );
  }

  return (
    <>
      <div
        className="synthetic-banner"
        role="banner"
        aria-label="Synthetic demo mode warning"
      >
        <div className="flex items-center gap-2">
          <AlertTriangle size={15} className="text-[var(--color-attention)]" aria-hidden="true" />
          <span className="font-bold tracking-wider">SYNTHETIC DEMO DATA</span>
          <span className="hidden sm:inline text-xs text-[var(--color-text-secondary)] font-normal">
            — Not connected to live execution cluster. Deterministic proof scenarios loaded.
          </span>
        </div>

        <div className="flex items-center gap-3">
          <label htmlFor="scenario-select" className="text-xs text-[var(--color-text-secondary)] hidden md:inline">
            Scenario:
          </label>
          <select
            id="scenario-select"
            value={activeScenario}
            onChange={handleScenarioChange}
            className="bg-[var(--color-surface-1)] text-[var(--color-text-primary)] border border-[var(--color-border-control)] text-xs rounded px-2 py-1 font-mono"
            aria-label="Select synthetic scenario"
          >
            <option value="NORMAL">Standard Showcase (Job 1111…)</option>
            <option value="SCENARIO_A_STALE_REJECTION">Scenario A: G5 Accepted / G4 Stale Rejection</option>
            <option value="SCENARIO_B_DEADLINE_PASSED">Scenario B: Deadline Passed / Awaiting Settlement</option>
            <option value="SCENARIO_C_RUNNING_WITH_FAILURE">Scenario C: RUNNING Job with FAILED Partition</option>
            <option value="SCENARIO_D_FAILED_WITH_PARTIAL">Scenario D: FAILED Job with Partial Acceptance</option>
            <option value="SCENARIO_E_NO_ACCEPTED_RESULT">Scenario E: Partition with No Accepted Result</option>
            <option value="SCENARIO_F_INTEGRITY_FAILURE">Scenario F: Integrity Failure Preserves Acceptance</option>
            <option value="SCENARIO_G_DISCONNECTED">Scenario G: Disconnected / Last-Known State</option>
            <option value="SCENARIO_H_CAPABILITY_GAP">Scenario H: Backend Capability Gap</option>
          </select>

          <button
            type="button"
            onClick={() => setShowPrereqModal(true)}
            className="btn-secondary text-xs py-0.5 px-2 h-7 inline-flex items-center gap-1 font-mono"
            title="Inspect live connection prerequisite (BV10)"
          >
            <Lock size={12} className="text-[var(--color-attention)]" aria-hidden="true" />
            <span>Live Connection (BV10)</span>
          </button>
        </div>
      </div>

      {/* BV10 Authentication Prerequisite Modal */}
      {showPrereqModal && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="bv10-modal-title"
        >
          <div className="bg-[var(--color-surface-1)] border border-[var(--color-border-control)] rounded-lg max-w-lg w-full p-5 space-y-4 shadow-xl">
            <div className="flex items-start justify-between pb-3 border-b border-[var(--color-border-subtle)]">
              <div className="flex items-center gap-2">
                <Lock size={18} className="text-[var(--color-attention)]" aria-hidden="true" />
                <h3 id="bv10-modal-title" className="text-sm font-semibold text-[var(--color-text-primary)]">
                  Live Connection Prerequisite: BV10 Browser Authentication
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setShowPrereqModal(false)}
                className="btn-icon text-[var(--color-text-secondary)]"
                aria-label="Close dialog"
              >
                <X size={16} aria-hidden="true" />
              </button>
            </div>

            <div className="space-y-3 text-xs text-[var(--color-text-secondary)] leading-relaxed">
              <p>
                Baseline Relay does not possess the approved browser authentication and session adapter (BV10: scoped operator session cookies, CSRF protection, and Origin header enforcement) required for authenticated operator reads.
              </p>
              <div className="p-3 rounded bg-[var(--color-surface-2)] border border-[var(--color-border-subtle)] font-mono text-[11px] space-y-1">
                <div className="text-[var(--color-text-muted)] font-semibold uppercase tracking-wider">
                  Operational Semantics:
                </div>
                <div>• Authenticated operator routes (<code className="text-[var(--color-text-primary)]">GET /v1/jobs/*</code>) require bearer operator token or BV10 session.</div>
                <div>• In Slice 1, authenticated live Job Detail is not usable without the BV10 adapter.</div>
                <div>• Unprotected endpoints (<code className="text-[var(--color-text-primary)]">/health/live</code>, <code className="text-[var(--color-text-primary)]">/health/ready</code>) can be probed, but do not grant operator access.</div>
              </div>
              <p className="text-[var(--color-text-muted)]">
                Switching out of synthetic mode clears synthetic observations and probes live cluster reachability, but live operator reads will report that BV10 browser authentication is required.
              </p>
            </div>

            <div className="pt-3 border-t border-[var(--color-border-subtle)] flex items-center justify-end gap-2 text-xs">
              <button
                type="button"
                onClick={() => setShowPrereqModal(false)}
                className="btn-primary"
              >
                Stay in Synthetic Demo
              </button>
              <button
                type="button"
                onClick={handleConfirmLive}
                className="btn-secondary"
              >
                Probe Unauthenticated Cluster
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
