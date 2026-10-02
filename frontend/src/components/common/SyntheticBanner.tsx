import React from 'react';
import { useRelay } from '../../context/RelayContext';
import { ScenarioKey } from '../../api/fixtureAdapter';
import { AlertTriangle, Database } from 'lucide-react';

export const SyntheticBanner: React.FC = () => {
  const { isSynthetic, activeScenario, setScenario, setSyntheticMode } = useRelay();

  if (!isSynthetic) {
    return null;
  }

  const handleScenarioChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setScenario(e.target.value as ScenarioKey);
  };

  return (
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
          onClick={() => setSyntheticMode(false)}
          className="btn-secondary text-xs py-0.5 px-2 h-7 inline-flex items-center gap-1"
          title="Switch to live backend mode"
        >
          <Database size={12} aria-hidden="true" />
          <span>Switch to Live</span>
        </button>
      </div>
    </div>
  );
};
