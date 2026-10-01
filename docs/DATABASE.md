# PostgreSQL schema and transaction contract

This is a declarative schema specification and transaction pseudocode, not migration or application code. Use READ COMMITTED plus explicit locks, one writable primary and synchronous_commit=on. UUID identifiers are opaque; counters use bigint; hashes are lowercase SHA-256 hex with format checks; timestamps use timestamptz. Foreign keys use RESTRICT, never cascading deletion of history. Runtime roles cannot delete durable entities. CHECK constraints bound integer fields and whitelist statuses. Application timestamps do not establish lease validity.

## Tables

### jobs

PK id UUID. Fields: version int CHECK =1, parent_job_id nullable FK jobs.id, status, definition_hash, workload_name, workload_version, workload_digest, parameters JSONB, manifest_hash, max_attempts int 1–10, lease_seconds int, max_attempt_seconds int, partition_count int 1–4096, next_event_seq bigint default 1, fair_ticket bigint, created_at, started_at nullable, finished_at nullable, cancellation_reason nullable. Immutable definition/policy fields after creation. No mutable success counters: counts derive from partitions under the job lock. Index (fair_ticket, created_at, id) WHERE status IN ('QUEUED','RUNNING'). No unique definition_hash: intentional reruns allowed. FK parent does not permit inherited mutable state.

### input_artifacts

PK id UUID. Fields: import_key text UNIQUE, reservation_fingerprint, expected_sha256, size_bytes, media_type, schema_hash, row_count nullable before verification, status RESERVED/VERIFIED/REJECTED, bucket, object_key UNIQUE, object_version nullable, sha256 nullable, created_at, verified_at nullable, error_code nullable. VERIFIED requires nonnull immutable version/hash/schema/row counts. UNIQUE(bucket, object_key, object_version). Import key is idempotent with the reservation fingerprint. Versioned objects are read-only; imports use the same conditional gateway protocol as outputs. No FK to jobs: inputs can be reused. Index (status, created_at) for reconciliation.

### job_inputs

PK (job_id, input_ordinal), FK job_id→jobs, input_artifact_id→input_artifacts. UNIQUE(job_id, input_artifact_id). Only VERIFIED inputs attach. Immutable after job creation. Created_at. No status/generation. This separates reusable input objects from job definitions.

### partitions

PK id UUID, job_id FK jobs, ordinal int >=0, status, generation bigint >=0 default 0, eligible_at, created_at, started_at nullable, finished_at nullable, last_error_code nullable. UNIQUE(job_id, ordinal), UNIQUE(id, job_id). Composite FK (id, generation)→attempts(partition_id, generation), DEFERRABLE INITIALLY DEFERRED, applies only for generation >0 via nullable latest_generation_fk maintained equal to generation when >0 (CHECK); generation 0 uses NULL. Index (job_id, eligible_at, ordinal) WHERE status='READY'; index (job_id,status). generation is the number of committed claims, not a clock. Cross-table max_attempts bound is a transition/constraint-trigger check.

### partition_inputs

PK (partition_id, slice_ordinal). partition_id FK partitions, job_id, input_ordinal, first_row bigint >=0, row_count bigint >=0, created_at. Composite FKs (partition_id,job_id)→partitions(id,job_id), (job_id,input_ordinal)→job_inputs. No status/generation. Ordered slices are immutable. Submission validator checks exact disjoint coverage of each input's [0,row_count), and records manifest_hash. Empty input has a single explicit empty slice. V1 rejects arbitrarily fragmented manifests exceeding descriptor size limits.

### workers

PK session_id UUID. Fields: display_name, registration_hash, session_secret_hash, state REGISTERED/DRAINING/STOPPED, deployment_workload_digest, last_heartbeat_seq bigint >=0, created_at, last_seen_at, stopped_at nullable. Index(last_seen_at) WHERE state<>'STOPPED'. No unique display_name. No attempt generation. Session authentication binds requests to session_id; request body alone is not identity. Worker state events use a separate session sequence below.

### attempts

PK id UUID. partition_id FK partitions; generation bigint >0; worker_session_id FK workers; status; claimed_at; lease_expires_at; hard_deadline_at; last_renew_seq bigint default 0; last_renew_fingerprint nullable; last_renew_response JSONB nullable; finished_at nullable; failure_code nullable; failure_detail bounded JSONB; failure_fingerprint nullable. UNIQUE(partition_id,generation), UNIQUE(id,partition_id,generation). Partial UNIQUE(partition_id) WHERE status='ACTIVE'; partial UNIQUE(worker_session_id) WHERE status='ACTIVE'. CHECK lease_expires_at<=hard_deadline_at and generation>0. Index(lease_expires_at,partition_id) WHERE status='ACTIVE'. Lease fields are on attempts, not duplicated on partitions. Identity and owner are immutable. Durable claim time sets hard_deadline_at=claimed_at+policy maximum; renewals cannot move it.

### artifacts

PK id UUID. attempt_id, partition_id, generation; composite FK to attempts(id,partition_id,generation). UNIQUE(attempt_id) (one output/attempt); UNIQUE(id,attempt_id,partition_id,generation); UNIQUE(bucket,object_key); UNIQUE(bucket,object_key,object_version). Fields: status RESERVED/VERIFIED/REJECTED, expected_sha256, expected_size_bytes, expected_schema_hash, reservation_fingerprint, bucket, object_key, object_version nullable, verified_sha256 nullable, verified_size_bytes nullable, verified_schema_hash nullable, created_at, verified_at nullable, rejection_code nullable. Index(status,created_at). VERIFIED requires all verification fields and exact expected/verified match. Identity and expected fields immutable. VERIFIED metadata cannot be updated or deleted by runtime role. Store object version is an opaque string, never inferred from a timestamp.

### accepted_results

PK partition_id FK partitions. attempt_id, generation, artifact_id UNIQUE; accepted_at; publication_fingerprint. Composite FK (attempt_id,partition_id,generation)→attempts(id,partition_id,generation); composite FK (artifact_id,attempt_id,partition_id,generation)→artifacts(id,attempt_id,partition_id,generation). UNIQUE(attempt_id). No mutable status, no update/delete grants; insert-only. A partition belongs to one immutable job version, so partition_id alone is the acceptance uniqueness scope. No UPSERT that replaces an existing row.

### events

PK (job_id,seq); job_id FK jobs; nullable partition_id with composite (partition_id,job_id) FK to partitions(id,job_id). Optional attempt identity uses three separate nullable fields: attempt_id, attempt_partition_id, attempt_generation, with MATCH FULL composite FK to attempts(id,partition_id,generation). CHECK all three are null or all three present; when present require partition_id IS NOT NULL and attempt_partition_id=partition_id. Thus partition-only and job-only events do not require an attempt. Fields: type, occurred_at, request_id, actor_type, actor_id, from_state, to_state, bounded details JSONB. Index(job_id,partition_id,seq). Append-only; no global sequence ordering claim. Under the job lock allocate next_event_seq, insert events, increment it atomically. Events within one mutation have a specified order: attempt, partition, result if applicable, job. Failed transactions consume no durable event sequence. Wall-clock timestamps are informational; seq establishes per-job commit order.

### worker_events

PK(session_id,seq); FK session_id→workers; type, occurred_at, request_id, details JSONB. workers also stores next_event_seq bigint. Append-only under worker row lock; records register/drain/stop, not every telemetry ping. Index(session_id,occurred_at). Worker events and job events have no shared total ordering.

### request_receipts

PK(scope,key), request_hash, operation, job_id nullable FK, worker_session_id nullable FK, attempt_id nullable FK, status_code, response JSONB, created_at. scope binds principal/session plus operation; key bounded 128 characters. Index(job_id), index(worker_session_id,created_at). Used for job submission and worker claim; also durable rejection receipts for publication request IDs. Immutable result per key. A receipt only exists for a committed operation. Same key/different payload: conflict. No expiry in V1. Natural keys handle cancel, artifact reservation, renew and accepted completion. Never store credentials or input data in receipts.

### scheduler_state

PK id CHECK=1; next_ticket bigint, updated_at. One durable row serializes **claim decisions only** and assignment of a new job's first ticket. Each new job or successful fresh claim takes current ticket and advances it. Initial job fair_ticket is a new ticket; successful claim moves job to the back. Never hold it for object I/O or execution. Counter overflow must fail closed before wraparound (operationally remote).

## Constraints beyond column checks

Migration-owned triggers reject immutable column changes, invalid state edges, result updates/deletes, and terminal reopening. Deferred constraint triggers on partitions, attempts and accepted_results enforce: RUNNING iff latest attempt is ACTIVE; SUCCEEDED iff result exists and matches latest SUCCEEDED attempt; latest generation equals greatest recorded attempt generation; READY/FAILED/CANCELLED have no ACTIVE attempt; accepted artifact VERIFIED; generation<=job.max_attempts. Job terminal consistency is checked at commit: SUCCEEDED all success; FAILED all terminal with ≥1 failure; CANCELLED no nonterminal partition. A nonterminal job with all partitions terminal is disallowed. These checks run only on affected jobs/partitions. Runtime writes are through one transition service; migration/admin credentials are separate. Do not claim ordinary CHECK constraints enforce cross-table invariants.

## Universal lock order

For operations needing them: scheduler_state → job → partition(s) ordered by ordinal → attempt(s) ordered by generation → worker → artifact → receipt. Operations may skip unneeded locks but never acquire earlier categories afterward. Worker registration/telemetry locks only worker and worker_events. Artifact verification locks only artifact after all storage I/O; it never requests job locks. Job submission gets scheduler lock, inserts new job and partitions. Recovery discovers candidate IDs without locks, then processes one partition per transaction with the common order. Never lock an attempt from the scan before its job. Expected duplicate-key insertion races roll back the transaction, then read the winner in a fresh transaction.

## Claim

1. Authenticate worker. Check existing claim receipt; same key/hash returns exact original response, even if its lease has since expired (client must inspect/revalidate before executing). Different hash conflicts.
2. BEGIN. Lock singleton scheduler row. Recheck receipt. Choose the lowest fair_ticket job with status QUEUED/RUNNING and an eligible READY partition using current DB time. Lock job; lock lowest eligible partition ordinal. Recheck eligibility and budget. Because global claim selection is serialized, do not use SKIP LOCKED here or claim bounded fairness from it. If candidate changes while locking, rescan under the scheduler lock. Locks time out rather than bypassing a hot job forever.
3. Lock worker. Require REGISTERED, matching deployment digest, and no ACTIVE attempt. A draining/stopped or busy session cannot claim. Missing telemetry alone is not a rejection: authenticated claim proves contact.
4. Sample clock_timestamp after locks. Increment partition.generation and its FK projection; insert ACTIVE attempt, lease=t+30s (job policy), hard deadline=t+maximum lifetime. Set partition RUNNING, first started_at if absent; set job RUNNING if first claim. Update fair_ticket using scheduler ticket, advance counter. Insert ordered events and claim receipt. Commit, then respond.
5. If no eligible partition, persist 204 receipt for that request key; new poll uses a new key. If response is lost, repeat that key. Never create another attempt on transport retry. Lock/DB timeout returns retryable error with no committed receipt.

Fairness: among a finite set of continuously eligible jobs, each successful claim moves its job behind all already eligible jobs. New arrivals join behind them. Thus they receive claim turns, subject to progressing transactions. No equal runtime fairness, no hard wall-clock starvation bound under outages, and one slow partition cannot be preempted. READY index supports eligible partition selection; job fair_ticket index supports job order; benchmark contention on singleton and job locks.

## Renew

Lock job, partition and attempt. Sample DB time after locks. Require job active, partition RUNNING, current attempt identity/generation/owner, attempt ACTIVE, t<lease_expires_at and t<hard_deadline_at. A duplicate or lower renew sequence never extends lease. Exact last sequence/fingerprint returns cached response only if still valid; older sequences return ignored/current lease. Higher seq sets lease=min(t+lease_duration, hard_deadline_at), saves response/fingerprint and emits LEASE_RENEWED. Equal sequence/different payload conflicts. Expired attempts always reject, including duplicate renews; stale renew acknowledgments cannot restore authority. Worker telemetry heartbeat is a different endpoint.

## Failure and expiry / bounded retry

Owner failure locks job/partition/attempt. Same failure fingerprint for an already FAILED attempt returns recorded disposition; it does not retry again. A different terminal request conflicts. For fresh failure require current owner and live ACTIVE attempt; expired request returns lease_expired and leaves recovery to settle it. Failure codes are server-classified: deterministic invalid input/schema/overflow is nonretryable; worker crash, store transient error and expiry are retryable. Arbitrary worker-supplied `retryable=true` is not authoritative.

Recovery samples candidates with ACTIVE status and lease_expires_at<=DB time using the partial index; process with ordered locks, resample time and recheck. On valid expiry set attempt EXPIRED. On valid failure set FAILED. If retryable and generation<max_attempts, set partition READY and eligible_at=t+backoff(generation); else FAILED with finished_at. Emit events and recompute job terminal status under its lock. Commit all changes together. Duplicate recovery/failure is a no-op or historical acknowledgment. Recovery does not claim, increment generation, or consume a worker slot.

## Artifact reserve, write, verify

Reserve under job/partition/attempt locks after checking live ownership; insert one artifact per attempt with gateway-chosen ID/key and immutable expected hash/size/schema. Exact repeat returns same reservation; altered expectation conflicts. Gateway performs conditional object creation, then reads that exact version and computes hash/schema outside DB locks. A lost write response is reconciled by reserved key; versioning and forbidden deletion mean the object cannot disappear/reappear through runtime operations. Record VERIFIED under artifact row lock with compare-and-set RESERVED→VERIFIED; duplicate verified metadata is identical or conflict. Permanent corruption marks REJECTED; worker reports failure, or expiry recovers if worker dies. Transient store failure leaves RESERVED. Verification may complete after cancellation/expiry; it grants no publication right.

## Publication — normative pseudocode

The public complete endpoint resolves the supplied artifact ID/URI to a known VERIFIED artifact; arbitrary URLs are rejected. Verification has already completed. `fingerprint` includes job, partition, attempt, generation, artifact ID, exact object version, size and SHA-256, but not request_id. Authenticated session must match recorded owner.

```text
publish_result(job, partition, attempt, generation, artifact_uri, artifact_hash):
  authenticate owner; resolve registered artifact; validate request fingerprint
  BEGIN
  lock job FOR UPDATE
  lock partition FOR UPDATE; verify partition belongs to job
  lock attempt FOR UPDATE; verify it belongs to partition and supplied generation
  if accepted_results[partition] exists:
      if same attempt + generation + artifact identity + fingerprint:
          return historic acceptance after transaction closes (200 replay)
      else: commit durable rejection receipt/event; return 409 stale_generation
            if supplied_generation < partition.generation, otherwise result_conflict
  lock artifact; require VERIFIED, exact attempt/partition/generation/hash binding
  t = clock_timestamp()  // fresh AFTER every potentially blocking lock
  conditional update partition RUNNING -> SUCCEEDED WHERE:
      job.status IN {QUEUED, RUNNING}
      AND partition.generation = supplied_generation
      AND attempt.id = supplied_attempt
      AND attempt.generation = partition.generation
      AND attempt.worker_session_id = authenticated_session
      AND attempt.status = ACTIVE
      AND t < attempt.lease_expires_at
      AND t < attempt.hard_deadline_at
      AND NOT EXISTS accepted_result(partition)
  require affected_rows = 1; otherwise no state mutation, record rejection
  insert accepted_results(partition, attempt, generation, artifact, t, fingerprint)
  set attempt SUCCEEDED, finished_at=t; set partition.finished_at=t
  recompute job terminal status from partitions while holding job lock
  append ATTEMPT_SUCCEEDED, PARTITION_SUCCEEDED, RESULT_ACCEPTED,
         then JOB_SUCCEEDED/JOB_FAILED if applicable
  COMMIT
  return accepted identity, accepted_at and current job status
```

The actual SQL must bind t once after locks, qualify all IDs, and test every predicate together. The conditional update's affected-row count is the ownership gate; the PK is a second cardinality barrier. Deferred constraints see the complete transaction. Never use `ON CONFLICT DO UPDATE` for accepted_results. Return success only after commit. Any DB exception rolls back all changes. Unknown commit outcome returns an uncertainty/retry response; retry same completion or GET the result, never assume failure and overwrite. Duplicate accepted completion is checked before current lease/job-status checks because it acknowledges a past event.

Rejection auditing: authenticated well-formed publication requests use request_id as a deduplication receipt key; one committed rejection event per distinct request_id. Repeat uses stored rejection; a caller trying again after correcting prerequisites uses a new ID. Successful replay is established by accepted_results independently of request_id. If DB is unavailable, rejection audit cannot be guaranteed: log locally and return 503 without claiming durable history.

## Cancel

Lock job. If CANCELLED return existing outcome; if SUCCEEDED/FAILED return 409 terminal_job. Lock all nonterminal partitions ascending ordinal and their ACTIVE attempts. Set attempts CANCELLED, partitions CANCELLED and finished timestamps; retain successful/failed partitions and all accepted_results. Set job CANCELLED, reason/finished_at. Emit attempt/partition events ascending ordinal then JOB_CANCELLED; commit. Every publication/claim/renew blocked on job lock rechecks terminal state afterward. No network calls or synchronous worker stop acknowledgment. Abort on timeout: partial cancellation cannot commit.

## Read consistency

GET job and counts use one SQL statement snapshot or a read-only REPEATABLE READ transaction. Events use per-job seq cursors. Partition pages sorted ordinal are individually consistent, not a snapshot across multiple requests. The status API exposes partial_result_count and complete=false for FAILED/CANCELLED jobs. Result reads use accepted_results→artifact exact version; storage failure never substitutes another object.
