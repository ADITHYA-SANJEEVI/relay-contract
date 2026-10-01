# Relay invariants and enforcement

Normative with SPEC.md. Safety must hold even when liveness fails. The trusted boundary excludes malicious database administrators and storage administrators.

| ID | Invariant | Enforcement | Evidence test |
|---|---|---|---|
| I01 | A partition's generation never decreases; each successful claim increases it by exactly one | Partition row lock; generation update and attempt insert in same transaction; unique partition/generation | T03, T06, T12 |
| I02 | At most one ACTIVE attempt per partition | Partial unique index on ACTIVE attempts; latest generation FK and transition checks | T06, T12 |
| I03 | A new acceptance requires current attempt, generation, owner session, ACTIVE state and unexpired lease/lifetime | Fenced publication predicate after locks, fresh DB time | T03, T04, T16 |
| I04 | At most one authoritative result per immutable partition | accepted_results PK partition_id, unique artifact_id, immutable result rows | T04, T05, T12 |
| I05 | Every accepted result points to a VERIFIED output of the same recorded attempt, partition and generation | Composite FKs, state guard and deferred consistency checks | T01, T17 |
| I06 | SUCCEEDED partition iff exactly one accepted result; its attempt is SUCCEEDED | Atomic publication and deferred consistency trigger | T01, T10, T11 |
| I07 | Terminal jobs/partitions/attempts cannot reopen | Transition whitelist; no runtime delete/reset; new job for rerun | T07–T09, T19 |
| I08 | Claim count never exceeds maximum attempts | Generation < max_attempts under job/partition locks; generation equals durable claim count | T09, T15 |
| I09 | Cancellation commit forbids later new acceptances for the job | Common job lock; synchronous cancellation of all nonterminal partitions | T07, T08 |
| I10 | Previously accepted results survive cancellation | Cancellation never updates successful partition/result rows | T08 |
| I11 | State changes and their events commit or roll back together | Event insertion in same transaction; job-local sequence under job lock | T10, T11, T14 |
| I12 | Duplicate requests cannot create additional claims or publications | Request deduplication, payload hash, natural unique result identity | T05, T06, T18 |
| I13 | Worker liveness telemetry cannot grant or restore ownership | Only claim grants ownership; renew requires existing live lease | T02, T16, T20 |
| I14 | Verified/accepted artifact identity and bytes cannot be changed through runtime APIs | Metadata transition guard, conditional writes, pinned versions, no delete permissions | T17, T21 |
| I15 | Job success requires every partition success; failure requires all partitions terminal and ≥1 failure | Terminal aggregation under common job lock | T13, T15 |
| I16 | Job definition, input snapshot and partition coverage are immutable | Write-once columns, disjoint manifest validation, digest | T22 |

## Safety argument for the central race

All state-mutating operations for a job acquire its row lock before touching any partition. A claim of generation 5 cannot commit until generation 4 has been made terminal (EXPIRED or FAILED). After generation 5 commits, generation 4 fails the latest-generation predicate even if its local clock, cached response or worker heartbeat says otherwise. After generation 5 publishes, the partition is terminal and the accepted_results primary key already exists. Generation 4 cannot satisfy the predicate or replace that row. Even before generation 5 exists, generation 4 is rejected when lease_expires_at <= freshly sampled DB time.

If generation 4 passes its fenced update while its lease is valid, and the transaction later commits after the deadline, it is the accepted attempt. Recovery was blocked behind its locks and cannot have reassigned it meanwhile. This is legal under the linearization contract; claiming rejection based on response-arrival time would be false.

## Cancellation ordering

Whichever conflicting job-locked transition commits first determines eligibility. If cancellation commits first, new publication is rejected. If publication commits first, it remains accepted and cancellation cancels only remaining work. If that publication finished the final partition, the job is SUCCEEDED and cancel returns terminal conflict. Failed or cancelled jobs are never silently reactivated. A repeated completion for an already accepted result returns that historic acceptance even if the job is now cancelled: it creates no new acceptance.

## Limits of proof

SQL uniqueness establishes cardinality, not every temporal condition. Runtime state changes must pass the single transition service and DB state guards. Arbitrary SQL with privileged credentials can defeat the protocol. Tests should exercise the actual service against PostgreSQL, including deliberately invalid DML under the runtime role. Successful tests support bounded claims; they do not establish fault tolerance against every possible failure.

Liveness additionally requires eventual DB/store availability, progressing DB time, recovery service execution, available compatible workers, finite transaction holding times, and a workload that finishes before attempt limits. Scheduler fairness is in claim turns, not equal CPU time or a wall-clock bound.
