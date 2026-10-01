# State machines

All unspecified transitions are invalid. Status values are checked text constants. All timestamps are DB-generated UTC timestamptz. Terminal rows remain queryable. Operation transaction protocol is in DATABASE.md.

## Job

| From | To | Trigger and precondition | Transaction |
|---|---|---|---|
| Absent | QUEUED | Valid immutable definition, ≥1 partition, unique submission key | Insert job, all partitions, submission receipt, event atomically |
| QUEUED | RUNNING | First valid claim | Claim transaction |
| QUEUED/RUNNING | CANCELLED | Authorized cancel wins job lock | Cancel job and every nonterminal partition/active attempt atomically |
| RUNNING | SUCCEEDED | Last unsettled partition succeeds; all partitions successful | Same transaction as last partition transition |
| RUNNING | FAILED | All partitions terminal; at least one FAILED | Same transaction as last partition transition |

Terminal: SUCCEEDED, FAILED, CANCELLED. Failure policy is **drain remaining work**, not fail-fast: one exhausted partition does not stop others. While remaining partitions are runnable/active the job stays RUNNING and reports failure counts. Job cancellation is logically immediate once committed, not a promise that all processes have stopped. No CANCELLING state is needed under the 4,096-partition cap. Large-job asynchronous cancellation is a later contract change.

## Partition

| From | To | Preconditions |
|---|---|---|
| Absent | READY | Atomic job creation; generation 0; eligible_at creation time |
| READY | RUNNING | Active job, eligible_at <= DB time, generation < max_attempts, valid free worker |
| RUNNING | SUCCEEDED | Current ACTIVE attempt publishes VERIFIED artifact with valid lease |
| RUNNING | READY | Current attempt fails/expires, attempts remain; set deterministic eligible_at |
| RUNNING | FAILED | Nonretryable failure, or current failure/expiry exhausts attempts |
| READY/RUNNING | CANCELLED | Job cancellation |

Terminal: SUCCEEDED, FAILED, CANCELLED. READY includes delayed retries; API returns eligible_at. A retry does not itself increment generation: the subsequent claim does. Latest generation remains as history while READY. No READY→READY retry transition and no manual retry endpoint.

## Attempt

| From | To | Preconditions |
|---|---|---|
| Absent | ACTIVE | New claim; next generation, owner session, initial lease |
| ACTIVE | ACTIVE | Valid lease renewal with higher sequence; no change of owner |
| ACTIVE | SUCCEEDED | Fenced publication |
| ACTIVE | FAILED | Owner reports valid failure before expiry, or allowed integrity/task error |
| ACTIVE | EXPIRED | Lease deadline or maximum lifetime reached, no earlier committed settlement |
| ACTIVE | CANCELLED | Job cancellation |

Terminal: SUCCEEDED, FAILED, EXPIRED, CANCELLED. Upload and artifact verification do not make an attempt successful and do not extend its lease. Duplicate terminal requests can be acknowledged without transitioning state. An expired failure/renew/publish request cannot reanimate an attempt; recovery will materialize EXPIRED if not already done. Failure code records cause separately from state.

An ACTIVE attempt implies its job is RUNNING: first claim changes both atomically. Renewal, fresh owner failure, artifact reservation and new publication require the canonical [live attempt ownership](SPEC.md#live-attempt-ownership--canonical-predicate) predicate; historical accepted replay remains an acknowledgment even after cancellation.

## Worker session

Each process boot has a new random session ID; display worker name is not ownership. Register retry reuses the same session ID and payload. A restarted process must use a new ID.

Persistent state: REGISTERED→DRAINING→STOPPED, or REGISTERED→STOPPED when no ACTIVE attempt. DRAINING denies new claims but allows current attempt renew/publication. STOPPED is terminal and permitted only after no ACTIVE attempt remains. Unreachable workers are not automatically marked STOPPED.

Liveness is a derived observation: FRESH if DB time minus last_seen_at < 30s; SUSPECT otherwise. REGISTERED/SUSPECT may become FRESH on a higher-sequence heartbeat; this grants no work. Telemetry heartbeats never renew attempt leases. A session may have at most one ACTIVE attempt (unique partial index). A restarted worker can claim under a new session while the old attempt remains leased; it cannot impersonate that old session.

## Artifact

RESERVED→VERIFIED on successful immutable object creation/reconciliation plus readback integrity and schema verification. RESERVED→REJECTED on permanent mismatch/corruption. VERIFIED and REJECTED metadata are terminal. Upload in progress is external activity, not durable ownership. Verified unaccepted artifacts are orphans and remain retained in V1. Later detected storage corruption returns an explicit integrity read failure and emits structured logs and appropriate metrics; it does not replace accepted metadata, substitute another object or automatically recompute a terminal partition. Durable, deduplicated, queryable integrity-incident persistence is deferred beyond V1.

## Concurrent operations

Claim, renew, fail, expiry, publication and cancellation all use the same job-before-partition lock order. Expiry versus renewal is resolved using fresh DB time after locks: a renew observed before the deadline may extend it; a renew evaluated at/after it must fail. A failure versus publication race allows only one ACTIVE→terminal transition. Storage I/O may overlap cancellation; upload may finish after cancellation, but publication is then forbidden. See DATABASE.md for duplicate handling before terminal guards.
