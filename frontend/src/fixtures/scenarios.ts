import { 
  JobSummary, 
  PartitionItem, 
  GenerationDetail, 
  AuthorityState, 
  RelayEvent,
  WorkerSession,
  CapabilityState
} from '../types/domain';

export const FIXTURE_OBSERVATION_TIME = '2026-10-03T02:00:00.000Z';

// Static deterministic IDs
export const JOB_ID_NORMAL = '11111111-1111-4111-8111-111111111111';
export const JOB_ID_FAILED_WITH_PARTIAL = '22222222-2222-4222-8222-222222222222';
export const JOB_ID_RUNNING_WITH_FAILURE = '33333333-3333-4333-8333-333333333333';

export const PARTITION_0_ID = 'aaaaaaaa-0000-4000-8000-000000000000';
export const PARTITION_1_ID = 'aaaaaaaa-1111-4000-8000-111111111111';
export const PARTITION_2_ID = 'aaaaaaaa-2222-4000-8000-222222222222';
export const PARTITION_3_ID = 'aaaaaaaa-3333-4000-8000-333333333333';
export const PARTITION_4_ID = 'aaaaaaaa-4444-4000-8000-444444444444';

export const ARTIFACT_G5_ID = 'bbbbbbbb-5555-4555-8555-555555555555';
export const ARTIFACT_G4_ID = 'bbbbbbbb-4444-4444-8444-444444444444';

export const ATTEMPT_G5_ID = 'cccccccc-5555-4555-8555-555555555555';
export const ATTEMPT_G4_ID = 'cccccccc-4444-4444-8444-444444444444';
export const ATTEMPT_ACTIVE_PAST_DEADLINE_ID = 'cccccccc-8888-4888-8888-888888888888';

export const WORKER_SESSION_1 = 'dddddddd-1111-4111-8111-111111111111';
export const WORKER_SESSION_2 = 'dddddddd-2222-4222-8222-222222222222';

/**
 * Scenario A:
 * Partition 0
 * G5: attempt SUCCEEDED, artifact VERIFIED, publication ACCEPTED
 * G4: attempt EXPIRED, artifact VERIFIED, publication REJECTED (reason: stale_generation)
 * G5 is authoritative, G4 remains EXPIRED and artifact remains VERIFIED.
 */
export const SCENARIO_A_GENERATIONS: GenerationDetail[] = [
  {
    generation: '5',
    attempt_id: ATTEMPT_G5_ID,
    partition_id: PARTITION_0_ID,
    worker_session_id: WORKER_SESSION_2,
    status: 'SUCCEEDED',
    claimed_at: '2026-10-03T01:50:00.000Z',
    lease_expires_at: '2026-10-03T01:51:30.000Z',
    hard_deadline_at: '2026-10-03T02:00:00.000Z',
    last_renew_seq: '4',
    finished_at: '2026-10-03T01:52:10.000Z',
    failure_code: null,
    artifact: {
      id: ARTIFACT_G5_ID,
      status: 'VERIFIED',
      sha256: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
      size_bytes: '1048576',
      schema_hash: '5f4dcc3b5aa765d61d8327deb882cf992b95991b7852b855e3b0c44298fc1c14',
      object_version: 'v2.5.final-g5'
    },
    publication: {
      status: 'ACCEPTED',
      accepted_at: '2026-10-03T01:52:12.000Z',
      fingerprint: '9a2f7c001234abcd5678ef0123456789abcdef0123456789abcdef0123456789'
    }
  },
  {
    generation: '4',
    attempt_id: ATTEMPT_G4_ID,
    partition_id: PARTITION_0_ID,
    worker_session_id: WORKER_SESSION_1,
    status: 'EXPIRED',
    claimed_at: '2026-10-03T01:45:00.000Z',
    lease_expires_at: '2026-10-03T01:45:30.000Z',
    hard_deadline_at: '2026-10-03T01:55:00.000Z',
    last_renew_seq: '1',
    finished_at: '2026-10-03T01:47:00.000Z',
    failure_code: null,
    artifact: {
      id: ARTIFACT_G4_ID,
      status: 'VERIFIED',
      sha256: 'ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb',
      size_bytes: '1048200',
      schema_hash: '5f4dcc3b5aa765d61d8327deb882cf992b95991b7852b855e3b0c44298fc1c14',
      object_version: 'v2.4.stale-g4'
    },
    publication: {
      status: 'REJECTED_STALE_GENERATION',
      rejection_reason: 'stale_generation'
    }
  },
  {
    generation: '3',
    attempt_id: 'cccccccc-3333-4333-8333-333333333333',
    partition_id: PARTITION_0_ID,
    worker_session_id: WORKER_SESSION_1,
    status: 'EXPIRED',
    claimed_at: '2026-10-03T01:40:00.000Z',
    lease_expires_at: '2026-10-03T01:40:30.000Z',
    hard_deadline_at: '2026-10-03T01:50:00.000Z',
    last_renew_seq: '0',
    finished_at: '2026-10-03T01:41:00.000Z',
    failure_code: null,
    artifact: null,
    publication: {
      status: 'NO_ACCEPTANCE_OBSERVED'
    }
  }
];

export const SCENARIO_A_AUTHORITY: AuthorityState = {
  status: 'ACCEPTED',
  partition_id: PARTITION_0_ID,
  partition_ordinal: 0,
  generation: '5',
  attempt_id: ATTEMPT_G5_ID,
  artifact_id: ARTIFACT_G5_ID,
  accepted_at: '2026-10-03T01:52:12.000Z',
  publication_fingerprint: '9a2f7c001234abcd5678ef0123456789abcdef0123456789abcdef0123456789'
};

/**
 * Scenario B:
 * Partition 1
 * ACTIVE attempt, deadline is in the past relative to fixture observation time
 * (Lease expired at 01:59:00, hard deadline at 01:59:30, observation time 02:00:00)
 * Backend has not yet committed EXPIRED.
 * Must render: ACTIVE + "Deadline passed · awaiting settlement"
 */
export const SCENARIO_B_GENERATIONS: GenerationDetail[] = [
  {
    generation: '1',
    attempt_id: ATTEMPT_ACTIVE_PAST_DEADLINE_ID,
    partition_id: PARTITION_1_ID,
    worker_session_id: WORKER_SESSION_1,
    status: 'ACTIVE',
    claimed_at: '2026-10-03T01:55:00.000Z',
    lease_expires_at: '2026-10-03T01:59:00.000Z',
    hard_deadline_at: '2026-10-03T01:59:30.000Z',
    last_renew_seq: '2',
    finished_at: null,
    failure_code: null,
    artifact: {
      id: 'bbbbbbbb-1111-4111-8111-111111111111',
      status: 'RESERVED'
    },
    publication: {
      status: 'NO_ACCEPTANCE_OBSERVED'
    }
  }
];

export const SCENARIO_B_AUTHORITY: AuthorityState = {
  status: 'NONE',
  partition_id: PARTITION_1_ID,
  partition_ordinal: 1
};

/**
 * Scenario C:
 * RUNNING job containing at least one FAILED partition.
 * Job status is RUNNING, not FAILED yet.
 */
export const SCENARIO_C_JOB: JobSummary = {
  id: JOB_ID_RUNNING_WITH_FAILURE,
  definition_hash: '4d868e8ccaa36b7582eb75b0ef337920ab7183e20e854fa16b04c86e08873099',
  status: 'RUNNING',
  created_at: '2026-10-03T01:30:00.000Z',
  started_at: '2026-10-03T01:30:02.000Z',
  finished_at: null,
  partition_count: '4',
  attempt_count: '6',
  partition_counts: {
    READY: '1',
    RUNNING: '1',
    SUCCEEDED: '1',
    FAILED: '1',
    CANCELLED: '0'
  },
  next_event_seq: '42',
  partial_result_count: '1',
  complete: false,
  workload_name: 'normalize_aggregate',
  workload_version: '1'
};

/**
 * Scenario D:
 * FAILED job retaining partial accepted outputs.
 * Job status is FAILED, partial_result_count > 0.
 */
export const SCENARIO_D_JOB: JobSummary = {
  id: JOB_ID_FAILED_WITH_PARTIAL,
  definition_hash: '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
  status: 'FAILED',
  created_at: '2026-10-03T01:00:00.000Z',
  started_at: '2026-10-03T01:00:05.000Z',
  finished_at: '2026-10-03T01:15:30.000Z',
  partition_count: '4',
  attempt_count: '7',
  partition_counts: {
    READY: '0',
    RUNNING: '0',
    SUCCEEDED: '2',
    FAILED: '2',
    CANCELLED: '0'
  },
  next_event_seq: '68',
  partial_result_count: '2',
  complete: false,
  workload_name: 'normalize_aggregate',
  workload_version: '1'
};

/**
 * Scenario E:
 * Partition with No accepted result.
 * Authority status: NONE
 */
export const SCENARIO_E_AUTHORITY: AuthorityState = {
  status: 'NONE',
  partition_id: PARTITION_2_ID,
  partition_ordinal: 2
};

/**
 * Scenario F:
 * Accepted relation exists, but explicit later content/integrity read failed.
 * Pinned content could not be verified on this read.
 * Authority remains ACCEPTED with green rail! Separate integrity warning banner.
 */
export const SCENARIO_F_AUTHORITY: AuthorityState = {
  status: 'ACCEPTED',
  partition_id: PARTITION_3_ID,
  partition_ordinal: 3,
  generation: '1',
  attempt_id: 'cccccccc-3333-4333-8333-999999999999',
  artifact_id: 'bbbbbbbb-3333-4333-8333-999999999999',
  accepted_at: '2026-10-03T01:45:00.000Z',
  publication_fingerprint: '3333333333333333333333333333333333333333333333333333333333333333',
  integrity_failure: {
    failed_at: '2026-10-03T02:00:00.000Z',
    request_id: 'req-integrity-err-992',
    error_message: 'Pinned content could not be verified on this read: object storage checksum mismatch'
  }
};

/**
 * Scenario G:
 * Disconnected / last-known state fixture
 */
export const SCENARIO_G_CONNECTION = {
  isLive: true,
  isSynthetic: false,
  apiReachable: false,
  readinessPassed: null,
  lastObservedAt: '2026-10-03T01:58:30.000Z',
  error: 'Connection refused: http://localhost:8000 (retaining last-known observation)',
  errorCode: 'network_error',
  statusCode: 0
};

/**
 * Scenario H:
 * Backend capability unavailable
 */
export const SCENARIO_H_CAPABILITY: CapabilityState = {
  code: 'BV03_PARTITION_HISTORY',
  title: 'BACKEND READ AVAILABLE (BV03) — BROWSER LIVE SESSION INTEGRATION PENDING',
  description: 'The R1 backend implements full historical attempt reads (BV03). However, consuming them in the browser requires the pending BV10 authentication adapter.',
  requiredReadContract: 'GET /v1/operator/partitions/{id}/history',
  isGap: true
};

/**
 * Standard Job for normal showcase (Scenario A + B + E)
 */
export const SCENARIO_NORMAL_JOB: JobSummary = {
  id: JOB_ID_NORMAL,
  definition_hash: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
  status: 'RUNNING',
  created_at: '2026-10-03T01:40:00.000Z',
  started_at: '2026-10-03T01:40:05.000Z',
  finished_at: null,
  partition_count: '4',
  attempt_count: '8',
  partition_counts: {
    READY: '0',
    RUNNING: '2',
    SUCCEEDED: '1',
    FAILED: '1',
    CANCELLED: '0'
  },
  next_event_seq: '85',
  partial_result_count: '1',
  complete: false,
  workload_name: 'normalize_aggregate',
  workload_version: '1'
};

export const SCENARIO_NORMAL_PARTITIONS: PartitionItem[] = [
  {
    id: PARTITION_0_ID,
    ordinal: 0,
    status: 'SUCCEEDED',
    generation: '5',
    eligible_at: null,
    last_error_code: null,
    attempt_id: ATTEMPT_G5_ID,
    lease_expires_at: '2026-10-03T01:51:30.000Z',
    hard_deadline_at: '2026-10-03T02:00:00.000Z',
    accepted_artifact_id: ARTIFACT_G5_ID,
    accepted_generation: '5',
    latest_attempt_status: 'SUCCEEDED'
  },
  {
    id: PARTITION_1_ID,
    ordinal: 1,
    status: 'RUNNING',
    generation: '1',
    eligible_at: null,
    last_error_code: null,
    attempt_id: ATTEMPT_ACTIVE_PAST_DEADLINE_ID,
    lease_expires_at: '2026-10-03T01:59:00.000Z',
    hard_deadline_at: '2026-10-03T01:59:30.000Z',
    accepted_artifact_id: null,
    accepted_generation: null,
    latest_attempt_status: 'ACTIVE'
  },
  {
    id: PARTITION_2_ID,
    ordinal: 2,
    status: 'RUNNING',
    generation: '2',
    eligible_at: null,
    last_error_code: null,
    attempt_id: 'cccccccc-2222-4222-8222-222222222222',
    lease_expires_at: '2026-10-03T02:00:30.000Z',
    hard_deadline_at: '2026-10-03T02:10:00.000Z',
    accepted_artifact_id: null,
    accepted_generation: null,
    latest_attempt_status: 'ACTIVE'
  },
  {
    id: PARTITION_3_ID,
    ordinal: 3,
    status: 'FAILED',
    generation: '3',
    eligible_at: null,
    last_error_code: 'worker_crash',
    attempt_id: 'cccccccc-3333-4333-8333-000000000000',
    lease_expires_at: '2026-10-03T01:48:00.000Z',
    hard_deadline_at: '2026-10-03T01:55:00.000Z',
    accepted_artifact_id: null,
    accepted_generation: null,
    latest_attempt_status: 'FAILED'
  }
];

export const SCENARIO_F_PARTITIONS: PartitionItem[] = [
  SCENARIO_NORMAL_PARTITIONS[0],
  SCENARIO_NORMAL_PARTITIONS[1],
  SCENARIO_NORMAL_PARTITIONS[2],
  {
    id: PARTITION_3_ID,
    ordinal: 3,
    status: 'SUCCEEDED',
    generation: '1',
    eligible_at: null,
    last_error_code: null,
    attempt_id: 'cccccccc-3333-4333-8333-999999999999',
    lease_expires_at: '2026-10-03T01:45:00.000Z',
    hard_deadline_at: '2026-10-03T01:50:00.000Z',
    accepted_artifact_id: 'bbbbbbbb-3333-4333-8333-999999999999',
    accepted_generation: '1',
    latest_attempt_status: 'SUCCEEDED'
  }
];

export const SCENARIO_C_PARTITIONS: PartitionItem[] = [
  {
    id: PARTITION_0_ID,
    ordinal: 0,
    status: 'SUCCEEDED',
    generation: '5',
    eligible_at: null,
    last_error_code: null,
    attempt_id: ATTEMPT_G5_ID,
    lease_expires_at: '2026-10-03T01:51:30.000Z',
    hard_deadline_at: '2026-10-03T02:00:00.000Z',
    accepted_artifact_id: ARTIFACT_G5_ID,
    accepted_generation: '5',
    latest_attempt_status: 'SUCCEEDED'
  },
  {
    id: PARTITION_1_ID,
    ordinal: 1,
    status: 'RUNNING',
    generation: '1',
    eligible_at: null,
    last_error_code: null,
    attempt_id: ATTEMPT_ACTIVE_PAST_DEADLINE_ID,
    lease_expires_at: '2026-10-03T01:59:00.000Z',
    hard_deadline_at: '2026-10-03T01:59:30.000Z',
    accepted_artifact_id: null,
    accepted_generation: null,
    latest_attempt_status: 'ACTIVE'
  },
  {
    id: PARTITION_2_ID,
    ordinal: 2,
    status: 'READY',
    generation: '0',
    eligible_at: null,
    last_error_code: null,
    attempt_id: null,
    lease_expires_at: null,
    hard_deadline_at: null,
    accepted_artifact_id: null,
    accepted_generation: null,
    latest_attempt_status: null
  },
  {
    id: PARTITION_3_ID,
    ordinal: 3,
    status: 'FAILED',
    generation: '3',
    eligible_at: null,
    last_error_code: 'worker_crash',
    attempt_id: 'cccccccc-3333-4333-8333-000000000000',
    lease_expires_at: '2026-10-03T01:48:00.000Z',
    hard_deadline_at: '2026-10-03T01:55:00.000Z',
    accepted_artifact_id: null,
    accepted_generation: null,
    latest_attempt_status: 'FAILED'
  }
];

export const SCENARIO_D_PARTITIONS: PartitionItem[] = [
  {
    id: PARTITION_0_ID,
    ordinal: 0,
    status: 'SUCCEEDED',
    generation: '5',
    eligible_at: null,
    last_error_code: null,
    attempt_id: ATTEMPT_G5_ID,
    lease_expires_at: '2026-10-03T01:51:30.000Z',
    hard_deadline_at: '2026-10-03T02:00:00.000Z',
    accepted_artifact_id: ARTIFACT_G5_ID,
    accepted_generation: '5',
    latest_attempt_status: 'SUCCEEDED'
  },
  {
    id: PARTITION_1_ID,
    ordinal: 1,
    status: 'SUCCEEDED',
    generation: '1',
    eligible_at: null,
    last_error_code: null,
    attempt_id: 'cccccccc-1111-4111-8111-111111111111',
    lease_expires_at: '2026-10-03T01:10:00.000Z',
    hard_deadline_at: '2026-10-03T01:15:00.000Z',
    accepted_artifact_id: 'bbbbbbbb-1111-4111-8111-111111111111',
    accepted_generation: '1',
    latest_attempt_status: 'SUCCEEDED'
  },
  {
    id: PARTITION_2_ID,
    ordinal: 2,
    status: 'FAILED',
    generation: '2',
    eligible_at: null,
    last_error_code: 'max_attempts_exceeded',
    attempt_id: 'cccccccc-2222-4222-8222-222222222222',
    lease_expires_at: '2026-10-03T01:12:00.000Z',
    hard_deadline_at: '2026-10-03T01:18:00.000Z',
    accepted_artifact_id: null,
    accepted_generation: null,
    latest_attempt_status: 'FAILED'
  },
  {
    id: PARTITION_3_ID,
    ordinal: 3,
    status: 'FAILED',
    generation: '3',
    eligible_at: null,
    last_error_code: 'worker_crash',
    attempt_id: 'cccccccc-3333-4333-8333-000000000000',
    lease_expires_at: '2026-10-03T01:14:00.000Z',
    hard_deadline_at: '2026-10-03T01:20:00.000Z',
    accepted_artifact_id: null,
    accepted_generation: null,
    latest_attempt_status: 'FAILED'
  }
];

export const SCENARIO_C_EVENTS: RelayEvent[] = [
  {
    job_id: JOB_ID_RUNNING_WITH_FAILURE,
    seq: '1',
    partition_id: null,
    attempt_id: null,
    attempt_generation: null,
    type: 'JOB_SUBMITTED',
    occurred_at: '2026-10-03T01:30:00.000Z',
    request_id: 'req-c-sub-001',
    actor_type: 'operator',
    actor_id: 'bootstrap-token-operator',
    from_state: null,
    to_state: 'QUEUED',
    details: { partition_count: 4, workload_name: 'normalize_aggregate' }
  },
  {
    job_id: JOB_ID_RUNNING_WITH_FAILURE,
    seq: '2',
    partition_id: null,
    attempt_id: null,
    attempt_generation: null,
    type: 'JOB_STARTED',
    occurred_at: '2026-10-03T01:30:02.000Z',
    request_id: null,
    actor_type: 'system',
    actor_id: 'scheduler',
    from_state: 'QUEUED',
    to_state: 'RUNNING',
    details: {}
  },
  {
    job_id: JOB_ID_RUNNING_WITH_FAILURE,
    seq: '3',
    partition_id: PARTITION_0_ID,
    partition_ordinal: 0,
    attempt_id: ATTEMPT_G5_ID,
    attempt_generation: '5',
    type: 'RESULT_ACCEPTED',
    occurred_at: '2026-10-03T01:32:00.000Z',
    request_id: 'req-c-pub-001',
    actor_type: 'control',
    actor_id: 'publication-service',
    from_state: 'RUNNING',
    to_state: 'SUCCEEDED',
    details: { artifact_id: ARTIFACT_G5_ID, generation: 5 }
  },
  {
    job_id: JOB_ID_RUNNING_WITH_FAILURE,
    seq: '4',
    partition_id: PARTITION_3_ID,
    partition_ordinal: 3,
    attempt_id: 'cccccccc-3333-4333-8333-000000000000',
    attempt_generation: '3',
    type: 'ATTEMPT_FAILED',
    occurred_at: '2026-10-03T01:35:00.000Z',
    request_id: null,
    actor_type: 'worker',
    actor_id: 'worker-node-prod-east-1c',
    from_state: 'RUNNING',
    to_state: 'FAILED',
    details: { error_code: 'worker_crash' }
  }
];

export const SCENARIO_D_EVENTS: RelayEvent[] = [
  {
    job_id: JOB_ID_FAILED_WITH_PARTIAL,
    seq: '1',
    partition_id: null,
    attempt_id: null,
    attempt_generation: null,
    type: 'JOB_SUBMITTED',
    occurred_at: '2026-10-03T01:00:00.000Z',
    request_id: 'req-d-sub-001',
    actor_type: 'operator',
    actor_id: 'bootstrap-token-operator',
    from_state: null,
    to_state: 'QUEUED',
    details: { partition_count: 4, workload_name: 'normalize_aggregate' }
  },
  {
    job_id: JOB_ID_FAILED_WITH_PARTIAL,
    seq: '2',
    partition_id: null,
    attempt_id: null,
    attempt_generation: null,
    type: 'JOB_STARTED',
    occurred_at: '2026-10-03T01:00:05.000Z',
    request_id: null,
    actor_type: 'system',
    actor_id: 'scheduler',
    from_state: 'QUEUED',
    to_state: 'RUNNING',
    details: {}
  },
  {
    job_id: JOB_ID_FAILED_WITH_PARTIAL,
    seq: '3',
    partition_id: PARTITION_0_ID,
    partition_ordinal: 0,
    attempt_id: ATTEMPT_G5_ID,
    attempt_generation: '5',
    type: 'RESULT_ACCEPTED',
    occurred_at: '2026-10-03T01:05:00.000Z',
    request_id: 'req-d-pub-001',
    actor_type: 'control',
    actor_id: 'publication-service',
    from_state: 'RUNNING',
    to_state: 'SUCCEEDED',
    details: { artifact_id: ARTIFACT_G5_ID, generation: 5 }
  },
  {
    job_id: JOB_ID_FAILED_WITH_PARTIAL,
    seq: '4',
    partition_id: PARTITION_1_ID,
    partition_ordinal: 1,
    attempt_id: 'cccccccc-1111-4111-8111-111111111111',
    attempt_generation: '1',
    type: 'RESULT_ACCEPTED',
    occurred_at: '2026-10-03T01:08:00.000Z',
    request_id: 'req-d-pub-002',
    actor_type: 'control',
    actor_id: 'publication-service',
    from_state: 'RUNNING',
    to_state: 'SUCCEEDED',
    details: { artifact_id: 'bbbbbbbb-1111-4111-8111-111111111111', generation: 1 }
  },
  {
    job_id: JOB_ID_FAILED_WITH_PARTIAL,
    seq: '5',
    partition_id: PARTITION_2_ID,
    partition_ordinal: 2,
    attempt_id: 'cccccccc-2222-4222-8222-222222222222',
    attempt_generation: '2',
    type: 'ATTEMPT_FAILED',
    occurred_at: '2026-10-03T01:10:00.000Z',
    request_id: null,
    actor_type: 'worker',
    actor_id: 'worker-node-prod-east-1a',
    from_state: 'RUNNING',
    to_state: 'FAILED',
    details: { error_code: 'max_attempts_exceeded' }
  },
  {
    job_id: JOB_ID_FAILED_WITH_PARTIAL,
    seq: '6',
    partition_id: PARTITION_3_ID,
    partition_ordinal: 3,
    attempt_id: 'cccccccc-3333-4333-8333-000000000000',
    attempt_generation: '3',
    type: 'ATTEMPT_FAILED',
    occurred_at: '2026-10-03T01:12:00.000Z',
    request_id: null,
    actor_type: 'worker',
    actor_id: 'worker-node-prod-east-1c',
    from_state: 'RUNNING',
    to_state: 'FAILED',
    details: { error_code: 'worker_crash' }
  },
  {
    job_id: JOB_ID_FAILED_WITH_PARTIAL,
    seq: '7',
    partition_id: null,
    attempt_id: null,
    attempt_generation: null,
    type: 'JOB_FAILED',
    occurred_at: '2026-10-03T01:15:30.000Z',
    request_id: null,
    actor_type: 'system',
    actor_id: 'scheduler',
    from_state: 'RUNNING',
    to_state: 'FAILED',
    details: { failed_partitions: 2, accepted_partitions: 2 }
  }
];

export const SCENARIO_NORMAL_EVENTS: RelayEvent[] = [
  {
    job_id: JOB_ID_NORMAL,
    seq: '1',
    partition_id: null,
    attempt_id: null,
    attempt_generation: null,
    type: 'JOB_SUBMITTED',
    occurred_at: '2026-10-03T01:40:00.000Z',
    request_id: 'req-sub-001',
    actor_type: 'operator',
    actor_id: 'bootstrap-token-operator',
    from_state: null,
    to_state: 'QUEUED',
    details: { partition_count: 4, workload_name: 'normalize_aggregate' }
  },
  {
    job_id: JOB_ID_NORMAL,
    seq: '2',
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
  },
  {
    job_id: JOB_ID_NORMAL,
    seq: '3',
    partition_id: PARTITION_0_ID,
    partition_ordinal: 0,
    attempt_id: 'cccccccc-3333-4333-8333-333333333333',
    attempt_generation: '3',
    type: 'ATTEMPT_CLAIMED',
    occurred_at: '2026-10-03T01:40:10.000Z',
    request_id: 'req-clm-001',
    actor_type: 'worker',
    actor_id: WORKER_SESSION_1,
    from_state: 'READY',
    to_state: 'RUNNING',
    details: { generation: 3 }
  },
  {
    job_id: JOB_ID_NORMAL,
    seq: '4',
    partition_id: PARTITION_0_ID,
    partition_ordinal: 0,
    attempt_id: 'cccccccc-3333-4333-8333-333333333333',
    attempt_generation: '3',
    type: 'ATTEMPT_EXPIRED',
    occurred_at: '2026-10-03T01:41:00.000Z',
    request_id: null,
    actor_type: 'system',
    actor_id: 'recovery-service',
    from_state: 'ACTIVE',
    to_state: 'EXPIRED',
    details: { reason: 'lease_timeout' }
  },
  {
    job_id: JOB_ID_NORMAL,
    seq: '5',
    partition_id: PARTITION_0_ID,
    partition_ordinal: 0,
    attempt_id: ATTEMPT_G4_ID,
    attempt_generation: '4',
    type: 'ATTEMPT_CLAIMED',
    occurred_at: '2026-10-03T01:45:00.000Z',
    request_id: 'req-clm-002',
    actor_type: 'worker',
    actor_id: WORKER_SESSION_1,
    from_state: 'READY',
    to_state: 'RUNNING',
    details: { generation: 4 }
  },
  // Consecutive renewal group in loaded range
  {
    job_id: JOB_ID_NORMAL,
    seq: '6',
    partition_id: PARTITION_0_ID,
    partition_ordinal: 0,
    attempt_id: ATTEMPT_G4_ID,
    attempt_generation: '4',
    type: 'LEASE_RENEWED',
    occurred_at: '2026-10-03T01:45:25.000Z',
    request_id: 'req-rnw-001',
    actor_type: 'worker',
    actor_id: WORKER_SESSION_1,
    from_state: 'ACTIVE',
    to_state: 'ACTIVE',
    details: { renew_seq: 1, extended_to: '2026-10-03T01:45:55.000Z' }
  },
  {
    job_id: JOB_ID_NORMAL,
    seq: '7',
    partition_id: PARTITION_0_ID,
    partition_ordinal: 0,
    attempt_id: ATTEMPT_G4_ID,
    attempt_generation: '4',
    type: 'LEASE_RENEWED',
    occurred_at: '2026-10-03T01:45:50.000Z',
    request_id: 'req-rnw-002',
    actor_type: 'worker',
    actor_id: WORKER_SESSION_1,
    from_state: 'ACTIVE',
    to_state: 'ACTIVE',
    details: { renew_seq: 2, extended_to: '2026-10-03T01:46:20.000Z' }
  },
  {
    job_id: JOB_ID_NORMAL,
    seq: '8',
    partition_id: PARTITION_0_ID,
    partition_ordinal: 0,
    attempt_id: ATTEMPT_G4_ID,
    attempt_generation: '4',
    type: 'ATTEMPT_EXPIRED',
    occurred_at: '2026-10-03T01:47:00.000Z',
    request_id: null,
    actor_type: 'system',
    actor_id: 'recovery-service',
    from_state: 'ACTIVE',
    to_state: 'EXPIRED',
    details: { reason: 'lease_timeout' }
  },
  {
    job_id: JOB_ID_NORMAL,
    seq: '9',
    partition_id: PARTITION_0_ID,
    partition_ordinal: 0,
    attempt_id: ATTEMPT_G5_ID,
    attempt_generation: '5',
    type: 'ATTEMPT_CLAIMED',
    occurred_at: '2026-10-03T01:50:00.000Z',
    request_id: 'req-clm-003',
    actor_type: 'worker',
    actor_id: WORKER_SESSION_2,
    from_state: 'READY',
    to_state: 'RUNNING',
    details: { generation: 5 }
  },
  {
    job_id: JOB_ID_NORMAL,
    seq: '10',
    partition_id: PARTITION_0_ID,
    partition_ordinal: 0,
    attempt_id: ATTEMPT_G5_ID,
    attempt_generation: '5',
    type: 'ARTIFACT_RESERVED',
    occurred_at: '2026-10-03T01:51:00.000Z',
    request_id: 'req-art-001',
    actor_type: 'worker',
    actor_id: WORKER_SESSION_2,
    from_state: null,
    to_state: 'RESERVED',
    details: { artifact_id: ARTIFACT_G5_ID }
  },
  {
    job_id: JOB_ID_NORMAL,
    seq: '11',
    partition_id: PARTITION_0_ID,
    partition_ordinal: 0,
    attempt_id: ATTEMPT_G5_ID,
    attempt_generation: '5',
    type: 'RESULT_ACCEPTED',
    occurred_at: '2026-10-03T01:52:12.000Z',
    request_id: 'req-pub-001',
    actor_type: 'control',
    actor_id: 'publication-service',
    from_state: 'RUNNING',
    to_state: 'SUCCEEDED',
    details: { artifact_id: ARTIFACT_G5_ID, generation: 5 }
  },
  {
    job_id: JOB_ID_NORMAL,
    seq: '12',
    partition_id: PARTITION_0_ID,
    partition_ordinal: 0,
    attempt_id: ATTEMPT_G4_ID,
    attempt_generation: '4',
    type: 'PUBLICATION_REJECTED',
    occurred_at: '2026-10-03T01:53:00.000Z',
    request_id: 'req-pub-stale-001',
    actor_type: 'control',
    actor_id: 'publication-service',
    from_state: 'EXPIRED',
    to_state: 'EXPIRED',
    details: { reason: 'stale_generation', attempted_generation: 4, current_generation: 5 }
  }
];

export const SCENARIO_WORKERS: WorkerSession[] = [
  {
    session_id: WORKER_SESSION_1,
    display_name: 'worker-node-prod-east-1a',
    state: 'REGISTERED',
    liveness: 'FRESH',
    last_seen_at: '2026-10-03T01:59:45.000Z',
    created_at: '2026-10-03T01:00:00.000Z',
    stopped_at: null,
    last_heartbeat_seq: '142',
    deployment_workload_digest: 'sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    current_attempt_id: ATTEMPT_ACTIVE_PAST_DEADLINE_ID,
    current_partition_ordinal: 1
  },
  {
    session_id: WORKER_SESSION_2,
    display_name: 'worker-node-prod-east-1b',
    state: 'REGISTERED',
    liveness: 'FRESH',
    last_seen_at: '2026-10-03T01:59:50.000Z',
    created_at: '2026-10-03T01:10:00.000Z',
    stopped_at: null,
    last_heartbeat_seq: '98',
    deployment_workload_digest: 'sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    current_attempt_id: null,
    current_partition_ordinal: null
  },
  {
    session_id: 'dddddddd-3333-4333-8333-333333333333',
    display_name: 'worker-node-prod-east-1c',
    state: 'REGISTERED',
    liveness: 'SUSPECT',
    last_seen_at: '2026-10-03T01:58:15.000Z', // > 30s ago -> SUSPECT, not crashed!
    created_at: '2026-10-03T01:15:00.000Z',
    stopped_at: null,
    last_heartbeat_seq: '56',
    deployment_workload_digest: 'sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    current_attempt_id: 'cccccccc-3333-4333-8333-000000000000',
    current_partition_ordinal: 3
  },
  {
    session_id: 'dddddddd-4444-4444-8444-444444444444',
    display_name: 'worker-node-old-session',
    state: 'STOPPED',
    liveness: 'NOT_APPLICABLE',
    last_seen_at: '2026-10-03T01:30:00.000Z',
    created_at: '2026-10-03T00:30:00.000Z',
    stopped_at: '2026-10-03T01:30:05.000Z',
    last_heartbeat_seq: '60',
    deployment_workload_digest: 'sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    current_attempt_id: null,
    current_partition_ordinal: null
  }
];
