/**
 * Authoritative Relay Control Board Domain Models
 *
 * Distinguishes four separate dimensions:
 * 1. RECORDED LIFECYCLE (committed database state)
 * 2. OBSERVED OWNERSHIP / DEADLINE STATE (time-relative observation)
 * 3. ARTIFACT VERIFICATION (bytes/schema integrity verification)
 * 4. RESULT AUTHORITY (explicit accepted relation)
 *
 * Invariants:
 * - VERIFIED != ACCEPTED
 * - STALE is not a stored attempt enum
 * - Highest generation != automatically authoritative
 * - Expired attempt can retain a VERIFIED artifact
 * - Active attempt past deadline remains ACTIVE awaiting settlement
 */

export type JobStatus = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED';

export type PartitionStatus = 'READY' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED';

export type AttemptStatus = 'ACTIVE' | 'EXPIRED' | 'FAILED' | 'SUCCEEDED' | 'CANCELLED';

export type ArtifactStatus = 'RESERVED' | 'VERIFIED' | 'REJECTED' | 'UNAVAILABLE';

export type PublicationStatus = 
  | 'ACCEPTED' 
  | 'REJECTED_STALE_GENERATION' 
  | 'REJECTED_KNOWN_CODE' 
  | 'NO_ACCEPTANCE_OBSERVED' 
  | 'UNKNOWN';

export type WorkerLifecycleState = 'REGISTERED' | 'DRAINING' | 'STOPPED';

export type WorkerLivenessState = 'FRESH' | 'SUSPECT' | 'NOT_APPLICABLE';

export type FailureCode = 
  | 'worker_crash'
  | 'store_transient'
  | 'transport_error'
  | 'input_invalid'
  | 'schema_mismatch'
  | 'workload_validation'
  | 'integer_overflow';

export interface PartitionCounts {
  READY: string;
  RUNNING: string;
  SUCCEEDED: string;
  FAILED: string;
  CANCELLED: string;
}

export interface JobSummary {
  id: string;
  definition_hash: string;
  status: JobStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  partition_count: string;
  attempt_count: string;
  partition_counts: PartitionCounts;
  next_event_seq: string;
  partial_result_count: string;
  complete: boolean;
  workload_name?: string;
  workload_version?: string;
}

export interface PartitionItem {
  id: string;
  ordinal: number;
  status: PartitionStatus;
  generation: string;
  eligible_at: string | null;
  last_error_code: string | null;
  attempt_id: string | null;
  lease_expires_at: string | null;
  hard_deadline_at: string | null;
  accepted_artifact_id: string | null;
  // enriched fields when available from history or fixture
  accepted_generation?: string | null;
  owning_worker_session?: string | null;
  latest_attempt_status?: AttemptStatus | null;
}

export interface GenerationDetail {
  generation: string;
  attempt_id: string;
  partition_id: string;
  worker_session_id: string | null;
  status: AttemptStatus;
  claimed_at: string;
  lease_expires_at: string;
  hard_deadline_at: string;
  last_renew_seq: string;
  finished_at: string | null;
  failure_code: string | null;
  // Artifact dimension
  artifact: {
    id: string;
    status: ArtifactStatus;
    sha256?: string;
    size_bytes?: string;
    schema_hash?: string;
    object_version?: string;
    rejection_code?: string;
  } | null;
  // Publication dimension
  publication: {
    status: PublicationStatus;
    rejection_reason?: string;
    accepted_at?: string;
    fingerprint?: string;
  };
}

export interface AuthorityState {
  status: 'ACCEPTED' | 'NONE' | 'UNKNOWN';
  partition_id: string;
  partition_ordinal: number;
  generation?: string;
  attempt_id?: string;
  artifact_id?: string;
  accepted_at?: string;
  publication_fingerprint?: string;
  integrity_failure?: {
    failed_at: string;
    request_id?: string;
    error_message: string;
  };
}

export interface RelayEvent {
  job_id: string;
  seq: string;
  partition_id: string | null;
  partition_ordinal?: number | null;
  attempt_id: string | null;
  attempt_generation: string | null;
  type: string;
  occurred_at: string;
  request_id: string | null;
  actor_type: string;
  actor_id: string;
  from_state: string | null;
  to_state: string | null;
  details: Record<string, unknown>;
}

export interface WorkerSession {
  session_id: string;
  display_name: string;
  state: WorkerLifecycleState;
  liveness: WorkerLivenessState;
  last_seen_at: string;
  created_at: string;
  stopped_at: string | null;
  last_heartbeat_seq: string;
  deployment_workload_digest: string;
  current_attempt_id: string | null;
  current_partition_ordinal: number | null;
}

export interface ConnectionStatus {
  isLive: boolean;
  isSynthetic: boolean;
  apiReachable: boolean | null;
  readinessPassed: boolean | null; // null if unchecked
  dbRevision?: string;
  lastObservedAt: string | null;
  error?: string | null;
  errorCode?: string | null;
  statusCode?: number | null;
}

export interface CapabilityState {
  code: string;
  title: string;
  description: string;
  requiredReadContract: string;
  isGap: boolean;
}
