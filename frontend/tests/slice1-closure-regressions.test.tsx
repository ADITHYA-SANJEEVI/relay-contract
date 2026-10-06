import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { LiveDataAdapter } from '../src/api/liveAdapter';
import { FixtureDataAdapter } from '../src/api/fixtureAdapter';
import { DefinitionTab } from '../src/components/job/DefinitionTab';
import { EventList } from '../src/components/job/EventList';
import { OverviewView } from '../src/views/OverviewView';
import { RelayProvider, useRelay } from '../src/context/RelayContext';
import {
  JOB_ID_NORMAL,
  JOB_ID_RUNNING_WITH_FAILURE,
  JOB_ID_FAILED_WITH_PARTIAL,
  SCENARIO_C_JOB,
  SCENARIO_D_JOB
} from '../src/fixtures/scenarios';
import { JobSummary, PartitionItem, RelayEvent } from '../src/types/domain';
import { PartitionTable } from '../src/components/job/PartitionTable';
import { AuthorityPanel } from '../src/components/common/AuthorityPanel';
import { PartitionInspector } from '../src/components/job/PartitionInspector';

describe('Relay Frontend Slice 1 Closure Pass Regressions', () => {
  // Requirement 3: Live Authority Attribution
  it('1. LiveDataAdapter.getAuthorityForPartition never infers latest attempt or generation as accepted', () => {
    const liveAdapter = new LiveDataAdapter();

    const samplePartition: PartitionItem = {
      id: 'p-ordinal-2',
      ordinal: 2,
      status: 'SUCCEEDED',
      generation: '4', // current generation
      eligible_at: null,
      last_error_code: null,
      attempt_id: 'att-latest-attempt-99', // latest attempt
      lease_expires_at: '2026-10-03T02:00:00Z',
      hard_deadline_at: '2026-10-03T02:10:00Z',
      accepted_artifact_id: 'art-accepted-output-11',
    };

    const authority = liveAdapter.getAuthorityForPartition(samplePartition);

    expect(authority.status).toBe('ACCEPTED');
    expect(authority.partition_id).toBe('p-ordinal-2');
    expect(authority.partition_ordinal).toBe(2);
    expect(authority.artifact_id).toBe('art-accepted-output-11');
    // Invariant: attempt_id and generation MUST NOT be inferred from latest attempt/generation
    expect(authority.attempt_id).toBeUndefined();
    expect(authority.generation).toBeUndefined();
  });

  // Requirement 4: Absent live definition fields are NOT filled with defaults
  it('2. DefinitionTab in live mode renders real definition_hash, BV09 gap, and no fabricated defaults', () => {
    const liveJobWithoutWorkload: JobSummary = {
      id: 'job-real-uuid-001',
      definition_hash: 'abc123def4567890abcdef1234567890abcdef1234567890abcdef1234567890',
      status: 'RUNNING',
      created_at: '2026-10-03T01:00:00Z',
      started_at: '2026-10-03T01:00:05Z',
      finished_at: null,
      partition_count: '16',
      attempt_count: '24',
      partition_counts: {
        READY: '0',
        RUNNING: '4',
        SUCCEEDED: '12',
        FAILED: '0',
        CANCELLED: '0'
      },
      next_event_seq: '95',
      partial_result_count: '12',
      complete: false
      // workload_name, workload_version, and policy are NOT exposed on live JobSummary
    };

    render(
      <RelayProvider defaultSynthetic={false}>
        <DefinitionTab job={liveJobWithoutWorkload} />
      </RelayProvider>
    );

    // Shows real definition hash
    expect(screen.getByText('abc123de…34567890')).toBeInTheDocument();
    // Shows real partition count
    expect(screen.getByText('16')).toBeInTheDocument();

    // Invariant: MUST NOT render fabricated defaults
    expect(screen.queryByText('normalize_aggregate')).not.toBeInTheDocument();
    expect(screen.queryByText('Default Max Attempts')).not.toBeInTheDocument();
    expect(screen.queryByText('Default Lease Seconds')).not.toBeInTheDocument();
    expect(screen.queryByText('Committed Raw Submission Descriptor')).not.toBeInTheDocument();

    // Renders BV09 capability notice
    expect(screen.getByText(/BACKEND READ AVAILABLE \(BV09\) — BROWSER LIVE SESSION INTEGRATION PENDING/)).toBeInTheDocument();
    expect(screen.getByText('GET /v1/jobs/{id}/definition')).toBeInTheDocument();
  });

  // Requirement 2: Live-Mode / BV10 Auth Honesty & observation clearing
  it('3. Switching to live mode clears synthetic observations and does not retain synthetic revision', () => {
    const TestModeSwitcher = () => {
      const { isSynthetic, setSyntheticMode, connectionStatus } = useRelay();
      return (
        <div>
          <span data-testid="isSynthetic">{isSynthetic ? 'SYNTHETIC' : 'LIVE'}</span>
          <span data-testid="apiReachable">{connectionStatus.apiReachable === null ? 'NULL' : String(connectionStatus.apiReachable)}</span>
          <span data-testid="readinessPassed">{connectionStatus.readinessPassed === null ? 'NULL' : String(connectionStatus.readinessPassed)}</span>
          <span data-testid="dbRevision">{connectionStatus.dbRevision || 'UNDEFINED'}</span>
          <button onClick={() => setSyntheticMode(false)}>Switch to Live</button>
        </div>
      );
    };

    render(
      <RelayProvider defaultSynthetic={true}>
        <TestModeSwitcher />
      </RelayProvider>
    );

    expect(screen.getByTestId('isSynthetic')).toHaveTextContent('SYNTHETIC');
    expect(screen.getByTestId('dbRevision')).toHaveTextContent('0002_readiness (synthetic)');

    // Trigger switch to live
    fireEvent.click(screen.getByText('Switch to Live'));

    expect(screen.getByTestId('isSynthetic')).toHaveTextContent('LIVE');
    // Invariant: Synthetic observations MUST NOT be retained!
    expect(screen.getByTestId('apiReachable')).toHaveTextContent('NULL');
    expect(screen.getByTestId('readinessPassed')).toHaveTextContent('NULL');
    expect(screen.getByTestId('dbRevision')).toHaveTextContent('UNDEFINED');
  });

  // Requirement 5: Fixtures Internally Consistent
  it('4. Fixture scenarios C and D have matching partitions, counts, and job-bound events', async () => {
    const adapter = new FixtureDataAdapter();

    // Scenario C check
    const cPartitions = await adapter.getPartitions(JOB_ID_RUNNING_WITH_FAILURE);
    expect(cPartitions.items.length).toBe(4);
    const cCounts = {
      READY: cPartitions.items.filter(p => p.status === 'READY').length,
      RUNNING: cPartitions.items.filter(p => p.status === 'RUNNING').length,
      SUCCEEDED: cPartitions.items.filter(p => p.status === 'SUCCEEDED').length,
      FAILED: cPartitions.items.filter(p => p.status === 'FAILED').length,
      CANCELLED: cPartitions.items.filter(p => p.status === 'CANCELLED').length,
    };
    expect(cCounts.READY).toBe(parseInt(SCENARIO_C_JOB.partition_counts.READY, 10));
    expect(cCounts.RUNNING).toBe(parseInt(SCENARIO_C_JOB.partition_counts.RUNNING, 10));
    expect(cCounts.SUCCEEDED).toBe(parseInt(SCENARIO_C_JOB.partition_counts.SUCCEEDED, 10));
    expect(cCounts.FAILED).toBe(parseInt(SCENARIO_C_JOB.partition_counts.FAILED, 10));

    const cAcceptedCount = cPartitions.items.filter(p => p.accepted_artifact_id !== null).length;
    expect(cAcceptedCount).toBe(parseInt(SCENARIO_C_JOB.partial_result_count, 10));

    const cEvents = await adapter.getEvents(JOB_ID_RUNNING_WITH_FAILURE);
    expect(cEvents.items.every(e => e.job_id === JOB_ID_RUNNING_WITH_FAILURE)).toBe(true);

    // Scenario D check
    const dPartitions = await adapter.getPartitions(JOB_ID_FAILED_WITH_PARTIAL);
    expect(dPartitions.items.length).toBe(4);
    const dCounts = {
      READY: dPartitions.items.filter(p => p.status === 'READY').length,
      RUNNING: dPartitions.items.filter(p => p.status === 'RUNNING').length,
      SUCCEEDED: dPartitions.items.filter(p => p.status === 'SUCCEEDED').length,
      FAILED: dPartitions.items.filter(p => p.status === 'FAILED').length,
      CANCELLED: dPartitions.items.filter(p => p.status === 'CANCELLED').length,
    };
    expect(dCounts.READY).toBe(parseInt(SCENARIO_D_JOB.partition_counts.READY, 10));
    expect(dCounts.RUNNING).toBe(parseInt(SCENARIO_D_JOB.partition_counts.RUNNING, 10));
    expect(dCounts.SUCCEEDED).toBe(parseInt(SCENARIO_D_JOB.partition_counts.SUCCEEDED, 10));
    expect(dCounts.FAILED).toBe(parseInt(SCENARIO_D_JOB.partition_counts.FAILED, 10));

    const dAcceptedCount = dPartitions.items.filter(p => p.accepted_artifact_id !== null).length;
    expect(dAcceptedCount).toBe(parseInt(SCENARIO_D_JOB.partial_result_count, 10));

    const dEvents = await adapter.getEvents(JOB_ID_FAILED_WITH_PARTIAL);
    expect(dEvents.items.every(e => e.job_id === JOB_ID_FAILED_WITH_PARTIAL)).toBe(true);

    // Partition identity binding in authority and generation details
    const auth = await adapter.getAuthorityForPartition('part-test-custom', 3);
    expect(auth.partition_id).toBe('part-test-custom');
    expect(auth.partition_ordinal).toBe(3);

    const gens = await adapter.getGenerationsForPartition('part-test-custom');
    if (gens.items.length > 0) {
      expect(gens.items.every(g => g.partition_id === 'part-test-custom')).toBe(true);
    }

    // Unknown synthetic job returns 404
    await expect(adapter.getJob('99999999-9999-4999-8999-999999999999')).rejects.toMatchObject({
      status: 404,
    });
  });

  // Requirement 6: Honest Event History Pagination and Range Bounds
  it('5. EventList displays bounded sequence range and pagination frontier indicators', () => {
    const sampleEvents: RelayEvent[] = [
      {
        job_id: JOB_ID_NORMAL,
        seq: '1',
        partition_id: null,
        attempt_id: null,
        attempt_generation: null,
        type: 'JOB_SUBMITTED',
        occurred_at: '2026-10-03T01:40:00.000Z',
        request_id: 'req-001',
        actor_type: 'operator',
        actor_id: 'admin',
        from_state: null,
        to_state: 'QUEUED',
        details: {}
      },
      {
        job_id: JOB_ID_NORMAL,
        seq: '4',
        partition_id: null,
        attempt_id: null,
        attempt_generation: null,
        type: 'JOB_STARTED',
        occurred_at: '2026-10-03T01:40:05.000Z',
        request_id: null,
        actor_type: 'system',
        actor_id: 'scheduler',
        from_state: 'QUEUED',
        to_state: 'RUNNING',
        details: {}
      }
    ];

    const onLoadMore = vi.fn();

    // Truncated stream with nextCursor
    const { rerender } = render(
      <EventList
        events={sampleEvents}
        nextCursor="4"
        onLoadMore={onLoadMore}
        isLoadingMore={false}
      />
    );

    expect(screen.getByText(/Loaded Sequence Range:/)).toBeInTheDocument();
    expect(screen.getByText('#1 – #4')).toBeInTheDocument();
    expect(screen.getByText('Stream Truncated (More Events Ahead)')).toBeInTheDocument();

    const loadBtn = screen.getByRole('button', { name: /Load Next Batch \(after seq #4\)/i });
    fireEvent.click(loadBtn);
    expect(onLoadMore).toHaveBeenCalledTimes(1);

    // Frontier stream (nextCursor === null)
    rerender(
      <EventList
        events={sampleEvents}
        nextCursor={null}
      />
    );

    expect(screen.getByText('At Stream Frontier')).toBeInTheDocument();
    expect(screen.getByText('All recorded stream events loaded up to sequence #4.')).toBeInTheDocument();
  });

  // Requirement 7: Eliminate unknown value fallbacks in OverviewView
  it('6. OverviewView renders Unavailable/Unknown instead of hardcoded 0002_readiness when unobserved', () => {
    render(
      <MemoryRouter>
        <RelayProvider defaultSynthetic={false}>
          <OverviewView />
        </RelayProvider>
      </MemoryRouter>
    );

    // In live mode with unobserved health:
    expect(screen.getByText('Unavailable')).toBeInTheDocument();
    expect(screen.getByText('Unknown')).toBeInTheDocument();
    // Must NOT contain fallback '0002_readiness'
    expect(screen.queryByText('0002_readiness')).not.toBeInTheDocument();
  });

  // Fix 1: Authority Consistency between PartitionTable and AuthorityPanel / Inspector
  it('7. Fix 1: Partition table and inspector consistently reflect accepted authority in Scenario F and Normal mode', async () => {
    const adapter = new FixtureDataAdapter();

    // 1. Scenario F: Integrity Failure Preserves Acceptance
    adapter.setScenario('SCENARIO_F_INTEGRITY_FAILURE');
    const fPartitions = await adapter.getPartitions('job-test-f');
    const fPart3 = fPartitions.items.find(p => p.ordinal === 3)!;
    expect(fPart3.accepted_artifact_id).toBeTruthy();
    expect(fPart3.accepted_generation).toBe('1');

    const fAuth3 = await adapter.getAuthorityForPartition(fPart3.id, 3);
    expect(fAuth3.status).toBe('ACCEPTED');
    expect(fAuth3.artifact_id).toBe(fPart3.accepted_artifact_id);
    expect(fAuth3.generation).toBe(fPart3.accepted_generation);
    expect(fAuth3.integrity_failure).toBeDefined();

    // Render table and inspector for Scenario F Partition 3
    const { unmount: unmountF } = render(
      <div>
        <PartitionTable
          partitions={fPartitions.items}
          selectedPartitionId={fPart3.id}
          onSelectPartition={() => {}}
          statusFilter="ALL"
          onChangeStatusFilter={() => {}}
          observedAt="2026-10-03T02:00:00Z"
        />
        <AuthorityPanel authority={fAuth3} />
      </div>
    );

    // Both table row and inspector must show Accepted (G1)
    expect(screen.getAllByText('Accepted').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Accepted result').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Pinned content could not be verified on this read')).toBeInTheDocument();
    expect(screen.getByText(/The accepted authority relation remains valid/i)).toBeInTheDocument();
    unmountF();

    // 2. Normal mode: Partition 3 (failed worker crash) has NO accepted result in table or inspector
    adapter.setScenario('NORMAL');
    const normalPartitions = await adapter.getPartitions(JOB_ID_NORMAL);
    const normalPart3 = normalPartitions.items.find(p => p.ordinal === 3)!;
    expect(normalPart3.accepted_artifact_id).toBeNull();

    const normalAuth3 = await adapter.getAuthorityForPartition(normalPart3.id, 3);
    expect(normalAuth3.status).toBe('NONE');

    const { unmount: unmountNormal } = render(
      <div>
        <PartitionTable
          partitions={normalPartitions.items}
          selectedPartitionId={normalPart3.id}
          onSelectPartition={() => {}}
          statusFilter="ALL"
          onChangeStatusFilter={() => {}}
          observedAt="2026-10-03T02:00:00Z"
        />
        <AuthorityPanel authority={normalAuth3} />
      </div>
    );

    // Table says None accepted (for partitions 1, 2, 3), inspector says No accepted result
    expect(screen.getAllByText('None accepted').length).toBe(3);
    expect(screen.getByText('No accepted result')).toBeInTheDocument();
    unmountNormal();
  });

  // Fix 2: Scenario H Visibly Demonstrates Backend Capability Gap
  it('8. Fix 2: Scenario H visibly renders CapabilityUnavailable for missing BV03 partition history', async () => {
    const adapter = new FixtureDataAdapter();
    adapter.setScenario('SCENARIO_H_CAPABILITY_GAP');

    await expect(adapter.getGenerationsForPartition('part-test-0')).rejects.toThrow(
      'CAPABILITY_GAP: BV03_PARTITION_HISTORY'
    );

    const gap = adapter.getCapabilityGap('BV03_PARTITION_HISTORY');
    expect(gap.code).toBe('BV03_PARTITION_HISTORY');
    expect(gap.isGap).toBe(true);

    const samplePartition: PartitionItem = {
      id: 'p-0',
      ordinal: 0,
      status: 'SUCCEEDED',
      generation: '5',
      eligible_at: null,
      last_error_code: null,
      attempt_id: 'att-1',
      lease_expires_at: null,
      hard_deadline_at: null,
      accepted_artifact_id: 'art-1',
      accepted_generation: '5',
      latest_attempt_status: 'SUCCEEDED'
    };

    render(
      <PartitionInspector
        partition={samplePartition}
        authority={{
          status: 'ACCEPTED',
          partition_id: 'p-0',
          partition_ordinal: 0,
          generation: '5',
          artifact_id: 'art-1',
          attempt_id: 'att-1'
        }}
        generations={[]}
        events={[]}
        observedAt="2026-10-03T02:00:00Z"
        historyGap={gap}
      />
    );

    // Visibly demonstrates the gap in the UI
    expect(screen.getByText('BACKEND READ AVAILABLE (BV03) — BROWSER LIVE SESSION INTEGRATION PENDING')).toBeInTheDocument();
    expect(screen.getByText(/The R1 backend implements full historical attempt reads \(BV03\)/)).toBeInTheDocument();
    expect(screen.getByText('GET /v1/operator/partitions/{id}/history')).toBeInTheDocument();
    expect(screen.getByText('(Pending BV10)')).toBeInTheDocument();
    // Must NOT say "0 recorded" or generic empty state
    expect(screen.queryByText('(0 recorded)')).not.toBeInTheDocument();
  });

  // Requirement 9: Responsive Table Closure
  it('9. Fix 3: Partition table gracefully hides secondary columns for narrow viewports', () => {
    const normalPartitions = [
      {
        id: 'part-responsive',
        ordinal: 0,
        status: 'SUCCEEDED' as const,
        generation: '1',
        attempt_id: 'att-res-1',
        lease_expires_at: null,
        hard_deadline_at: null,
        accepted_artifact_id: 'art-res',
        latest_attempt_status: 'SUCCEEDED' as const,
        eligible_at: null,
        last_error_code: null
      }
    ];

    render(
      <PartitionTable
        partitions={normalPartitions}
        selectedPartitionId={null}
        onSelectPartition={() => {}}
        statusFilter="ALL"
        onChangeStatusFilter={() => {}}
        observedAt="2026-10-03T02:00:00Z"
      />
    );

    // Verify desktop columns are present but have the right hidden classes
    const latestAttemptHeader = screen.getByRole('columnheader', { name: /Latest Attempt/i });
    expect(latestAttemptHeader).toHaveClass('hidden lg:table-cell');

    const leaseHeader = screen.getByRole('columnheader', { name: /Lease \/ Deadline/i });
    expect(leaseHeader).toHaveClass('hidden lg:table-cell');

    const lastErrorHeader = screen.getByRole('columnheader', { name: /Last Error/i });
    expect(lastErrorHeader).toHaveClass('hidden md:table-cell');

    // The core info must remain visible without hidden classes
    const statusHeader = screen.getByRole('columnheader', { name: /Status/i });
    expect(statusHeader).not.toHaveClass('hidden lg:table-cell');
    
    const acceptedHeader = screen.getByRole('columnheader', { name: /Accepted Result/i });
    expect(acceptedHeader).not.toHaveClass('hidden lg:table-cell');
  });
});
