import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AuthorityPanel } from '../src/components/common/AuthorityPanel';
import { GenerationCard } from '../src/components/job/GenerationCard';
import { RecordedStatusBadge, ArtifactStatusBadge, ObservationBadge } from '../src/components/common/StatusBadges';
import { JobHeader } from '../src/components/job/JobHeader';
import { JobSummaryStrip } from '../src/components/job/JobSummaryStrip';
import { CapabilityUnavailable } from '../src/components/common/CapabilityUnavailable';
import { 
  SCENARIO_A_GENERATIONS, 
  SCENARIO_B_GENERATIONS, 
  SCENARIO_C_JOB, 
  SCENARIO_D_JOB, 
  SCENARIO_E_AUTHORITY, 
  SCENARIO_F_AUTHORITY 
} from '../src/fixtures/scenarios';
import { AuthorityState, GenerationDetail } from '../src/types/domain';

describe('Relay Authority and Semantic Invariants', () => {
  // Test 1: VERIFIED artifact remains distinct from ACCEPTED authority
  it('1. VERIFIED artifact remains distinct from ACCEPTED authority', () => {
    // Render an artifact badge with VERIFIED
    const { rerender } = render(<ArtifactStatusBadge status="VERIFIED" />);
    expect(screen.getByText('VERIFIED')).toBeInTheDocument();

    // Now render an unaccepted authority panel (status: NONE)
    rerender(<AuthorityPanel authority={{ status: 'NONE', partition_id: 'p1', partition_ordinal: 1 }} />);
    expect(screen.getByText('No accepted result')).toBeInTheDocument();
    expect(screen.queryByText('Accepted result')).not.toBeInTheDocument();
  });

  // Test 2: G4 EXPIRED, VERIFIED, stale publication rejection while G5 is ACCEPTED
  it('2. G4 EXPIRED, VERIFIED, stale publication rejection while G5 is ACCEPTED', () => {
    const g5 = SCENARIO_A_GENERATIONS.find(g => g.generation === '5')!;
    const g4 = SCENARIO_A_GENERATIONS.find(g => g.generation === '4')!;

    // Render G5
    const { rerender } = render(<GenerationCard generation={g5} />);
    expect(screen.getByText('G5')).toBeInTheDocument();
    expect(screen.getByText('SUCCEEDED')).toBeInTheDocument();
    expect(screen.getByText('VERIFIED')).toBeInTheDocument();
    expect(screen.getByText('ACCEPTED · authoritative')).toBeInTheDocument();

    // Render G4
    rerender(<GenerationCard generation={g4} />);
    expect(screen.getByText('G4')).toBeInTheDocument();
    // Invariant: G4 must remain EXPIRED, not rewritten to STALE or FAILED
    expect(screen.getByText('EXPIRED')).toBeInTheDocument();
    expect(screen.queryByText('STALE')).not.toBeInTheDocument();
    // Artifact remains VERIFIED
    expect(screen.getByText('VERIFIED')).toBeInTheDocument();
    // Publication is REJECTED · stale_generation
    expect(screen.getByText('REJECTED · stale_generation')).toBeInTheDocument();
  });

  // Test 3: deadline-passed ACTIVE remains ACTIVE
  it('3. deadline-passed ACTIVE remains ACTIVE', () => {
    // When ACTIVE attempt lease is in the past, status remains ACTIVE, but observation badge notes deadline passed
    const g1 = SCENARIO_B_GENERATIONS[0];
    expect(g1.status).toBe('ACTIVE');

    render(
      <div>
        <RecordedStatusBadge status={g1.status} type="attempt" />
        <ObservationBadge isDeadlinePassed={true} attemptStatus="ACTIVE" />
      </div>
    );

    expect(screen.getByText('ACTIVE')).toBeInTheDocument();
    expect(screen.queryByText('EXPIRED')).not.toBeInTheDocument();
    expect(screen.getByText('Deadline passed · awaiting settlement')).toBeInTheDocument();
  });

  // Test 4: FAILED job retains partial accepted output
  it('4. FAILED job retains partial accepted output', () => {
    render(
      <div>
        <JobHeader job={SCENARIO_D_JOB} onRefresh={() => {}} />
        <JobSummaryStrip job={SCENARIO_D_JOB} observedAt="2026-10-03T02:00:00Z" />
      </div>
    );

    expect(screen.getByText('Job failed · partial accepted results retained')).toBeInTheDocument();
    expect(screen.getByText('2 / 4 (50%)')).toBeInTheDocument();
  });

  // Test 5: RUNNING job can contain FAILED partition
  it('5. RUNNING job can contain FAILED partition', () => {
    render(
      <div>
        <JobHeader job={SCENARIO_C_JOB} onRefresh={() => {}} />
        <JobSummaryStrip job={SCENARIO_C_JOB} observedAt="2026-10-03T02:00:00Z" />
      </div>
    );

    expect(screen.getByText('RUNNING')).toBeInTheDocument();
    expect(screen.getByText('Work continues; failed partitions will make final outcome FAILED')).toBeInTheDocument();
    // FAILED partition count is 1
    const ones = screen.getAllByText('1');
    expect(ones.length).toBeGreaterThanOrEqual(1);
  });

  // Test 6: no accepted result renders neutral AuthorityPanel
  it('6. no accepted result renders neutral AuthorityPanel', () => {
    const { container } = render(<AuthorityPanel authority={SCENARIO_E_AUTHORITY} />);
    expect(screen.getByText('No accepted result')).toBeInTheDocument();
    expect(screen.queryByText('Accepted result')).not.toBeInTheDocument();
    expect(container.querySelector('.authority-rail-accepted')).toBeNull();
  });

  // Test 7: unknown authority differs from no accepted result
  it('7. unknown authority differs from no accepted result', () => {
    const unknownAuth: AuthorityState = {
      status: 'UNKNOWN',
      partition_id: 'p-unk',
      partition_ordinal: 5
    };

    const { rerender } = render(<AuthorityPanel authority={unknownAuth} />);
    expect(screen.getByText('Authority state unavailable')).toBeInTheDocument();
    expect(screen.queryByText('No accepted result')).not.toBeInTheDocument();

    rerender(<AuthorityPanel authority={SCENARIO_E_AUTHORITY} />);
    expect(screen.getByText('No accepted result')).toBeInTheDocument();
    expect(screen.queryByText('Authority state unavailable')).not.toBeInTheDocument();
  });

  // Test 8: missing capability differs from empty result
  it('8. missing capability differs from empty result', () => {
    render(
      <CapabilityUnavailable
        title="Complete Partition Attempt History"
        description="Historical attempts are not exposed by the current baseline read contract."
        requiredReadContract="GET /v1/operator/partitions/{id}"
      />
    );

    expect(screen.getByText('Complete Partition Attempt History')).toBeInTheDocument();
    expect(screen.getByText('GET /v1/operator/partitions/{id}')).toBeInTheDocument();
    expect(screen.queryByText('No attempts found')).not.toBeInTheDocument();
  });

  // Test 15: integrity-read failure preserves accepted relation
  it('15. integrity-read failure preserves accepted relation', () => {
    const { container } = render(<AuthorityPanel authority={SCENARIO_F_AUTHORITY} />);
    
    // Authority rail must remain green and marked Accepted
    expect(container.querySelector('.authority-rail-accepted')).not.toBeNull();
    expect(screen.getByText('Accepted result')).toBeInTheDocument();
    // Separate integrity warning displayed
    expect(screen.getByText('Pinned content could not be verified on this read')).toBeInTheDocument();
  });

  // Test 17: unsupported enum does not map to success
  it('17. unsupported enum does not map to success', () => {
    render(<RecordedStatusBadge status="UNRECOGNIZED_FUTURE_ENUM" type="partition" />);
    expect(screen.getByText(/Unsupported \/ unknown state/)).toBeInTheDocument();
    expect(screen.queryByText('SUCCEEDED')).not.toBeInTheDocument();
    expect(screen.queryByText('Accepted result')).not.toBeInTheDocument();
  });

  // Test 18: generation stack preserves independent lifecycle/artifact/publication dimensions
  it('18. generation stack preserves independent lifecycle/artifact/publication dimensions', () => {
    const testGen: GenerationDetail = {
      generation: '4',
      attempt_id: 'att-123',
      partition_id: 'part-123',
      worker_session_id: 'w-1',
      status: 'EXPIRED',
      claimed_at: '2026-10-03T01:00:00Z',
      lease_expires_at: '2026-10-03T01:00:30Z',
      hard_deadline_at: '2026-10-03T01:10:00Z',
      last_renew_seq: '0',
      finished_at: '2026-10-03T01:02:00Z',
      failure_code: null,
      artifact: {
        id: 'art-123',
        status: 'VERIFIED'
      },
      publication: {
        status: 'REJECTED_STALE_GENERATION'
      }
    };

    render(<GenerationCard generation={testGen} />);

    // Check that all 3 dimension labels and their respective values are present simultaneously
    expect(screen.getByText('Attempt Lifecycle:')).toBeInTheDocument();
    expect(screen.getByText('EXPIRED')).toBeInTheDocument();

    expect(screen.getByText('Artifact Verification:')).toBeInTheDocument();
    expect(screen.getByText('VERIFIED')).toBeInTheDocument();

    expect(screen.getByText('Publication Outcome:')).toBeInTheDocument();
    expect(screen.getByText('REJECTED · stale_generation')).toBeInTheDocument();
  });
});
