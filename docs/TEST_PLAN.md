# Correctness tests and deterministic fault injection

The runtime scenarios T01–T27 below remain planned and unimplemented. M0's infrastructure/storage tests are separate, under tests/infrastructure and tests/storage_contract; observed results are recorded in M0_EVIDENCE.md. This plan is the acceptance contract for runtime implementation. Use real PostgreSQL and the selected object store in isolated Compose projects. Every runtime test checks both API outcomes and database invariants, plus exact accepted output identity/content where relevant. Do not substitute mocks/SQLite for lock/transaction tests. Unit tests cover pure validation and workload transforms; integration tests establish protocol behavior.

## Harness

Test-only named barriers: AFTER_CLAIM_COMMIT, BEFORE_EXECUTE, MID_EXECUTE, AFTER_ARTIFACT_PUT, AFTER_ARTIFACT_VERIFIED, BEFORE_PUBLISH_LOCK, AFTER_PUBLISH_LOCKS_BEFORE_CLOCK, AFTER_FENCED_UPDATE_BEFORE_COMMIT, AFTER_PUBLISH_COMMIT_BEFORE_RESPONSE, BEFORE_RENEW, AFTER_CANCEL_JOB_LOCK. Each emits a token `{run_id,job_id,partition_ordinal,generation,worker_session,phase}` to the harness and waits for explicit release. Control channels are enabled only in test builds/localhost test configuration; not public API endpoints.

Scripted actions: kill worker process/container, SIGSTOP/SIGCONT whole worker container, delay/drop selected renew sequence, force selected workload error, fail gateway write, hold publication barrier, kill after artifact write, close connection after commit before response. Whole-process pause must also stop supervisor renewals; pausing only a child simulates a hung task instead. On Windows run signal scenarios inside Linux containers.

Main deterministic suite advances lease state through a test-only DB fixture under the normal job/partition lock order, moving deadlines into the past without modifying production clock code. It never fabricates successful results or deletes generations. Separate real-clock tests use short configured leases and bounded polling to confirm actual DB-clock behavior. Sleeps do not coordinate races; barriers do. Harness records every action and outcome. Post-lock expiry test may wait to cross a short deadline intentionally, as distinct from scheduler timing assumptions.

## Required scenarios

| Test | Controlled scenario | Required assertions |
|---|---|---|
| T01 | Normal multi-partition execution | All oracle outputs match; one result per partition; all events/state constraints hold; job SUCCEEDED |
| T02 | Kill after claim and mid-execution | Expiry frees ownership; retry recovers; old generation terminal; no authority from partial output |
| T03 | Expire lease, recover, reassign | Generation increases exactly once per new claim; owner changes; heartbeat cannot resurrect old owner |
| T04 | Exact generation 4/5 stale scenario below | Old completion 409; generation 5 remains sole accepted result |
| T05 | Concurrent identical and conflicting complete requests | Exactly one acceptance/event set; identical repeats 200; changed identity 409; no duplicate success |
| T06 | Repeated claim key and concurrent different keys | Same key same attempt; one ACTIVE attempt per session and partition; conflicting body 409 |
| T07 | Cancel before claim and during execution | No post-cancel claim/renew/new acceptance; worker stop best-effort; terminal states immutable |
| T08 | Both publication/cancellation orderings plus last-partition case | Cancel-first rejects; publish-first retained; last success-first cancel conflicts; rollback winner lets loser proceed |
| T09 | Repeated retryable failure to max_attempts | Exactly configured number of claims; partition/job terminal; duplicate failure does not requeue |
| T10 | Upload then fail publication before commit | No result/event success; verified artifact retained; retry succeeds only with valid ownership |
| T11 | Commit then drop response | Retry after expiry returns original success; accepted_at/hash unchanged; no second success event |
| T12 | 32 workers race for one partition | One claim wins; all others receive no work or retryable contention, no duplicate ACTIVE generation |
| T13 | Many partitions/many workers; 4,096 cap case | Complete coverage, uniqueness, bounded transactions, no silent skipped partitions; fairness probe included |
| T14 | Restart API and recovery at barriers | Durable receipts/state survive; abandoned transactions roll back; new API reconciles uploads/claims |
| T15 | Poison partition beside healthy partitions | Healthy work drains; poison fails immediately for nonretryable or exhausts retryable cap; job FAILED only when all terminal |
| T16 | Expired before recovery; expiry while waiting for locks; duplicate/delayed renew | No fresh acceptance or renewal at/after deadline; no transaction-start clock loophole; lower renew seq never extends |
| T17 | Corrupt/missing/wrong-attempt/wrong-version artifact | Publication refused; FKs reject cross-partition bindings; later corruption yields explicit pinned-version integrity failure/logs/metrics without metadata replacement, substitution or automatic recomputation; durable incident persistence deferred |
| T18 | Drop claim response; retry key; delayed retry after expiry | Original attempt returned; no extra generation; replay does not authorize execution |
| T19 | Invalid DML with runtime role; terminal reopen attempts | Immutability, FK, unique and transition/deferred guards reject invalid rows |
| T20 | Worker restart and duplicate telemetry | New session owns only own work; prior session ID not reused; duplicate heartbeat not renewal |
| T21 | Concurrent store conditional writes, upload lost reply, object metadata update/delete attempts | At most one immutable object identity; reserved-key reconciliation; runtime cannot delete/replace accepted bytes |
| T22 | Mutable input, overlapping/gapped manifest, invalid schema and duplicate submission | Rejections before partial job creation; fixed input versions and exact idempotency |
| T23 | Failure races publication; renewal races recovery | One terminal disposition; ordering respects current locked DB time |
| T24 | Task child hangs while supervisor alive | Absolute attempt deadline stops perpetual renewal and yields bounded retries |
| T25 | DB disconnect during commit, store outage, full output quota | Outcome uncertainty handled by read/retry; never advertise uncommitted success |
| T26 | Publication crosses deadline AFTER valid fenced mutation while locks held | Committed result permitted; recovery cannot reassign; explicitly validates linearization definition |
| T27 | Events under aborted/concurrent transactions | Durable per-job seq ordering; no success events for abort; repeated rejected request ID not double-counted |

## Exact stale-worker reproduction

1. Job has one partition ordinal 17 in a fixture manifest that also includes preceding ordinals as needed; max_attempts at least 5. Generate and expire attempts 1, 2, 3 through normal claim/recovery transitions; advance retry eligibility via test fixture.
2. Worker A claims generation 4, executes and verifies artifact A, then pauses BEFORE_PUBLISH_LOCK. Pause its renewal supervisor too.
3. Expire generation 4 through fixture (plus a separate real-time variant). Run recovery, assert attempt EXPIRED and partition READY. Advance backoff eligibility.
4. Worker B claims generation 5; computes/verifies artifact B; publishes; assert result points to B, generation 5 and exact hash.
5. Release A and send completion for generation 4. Assert 409 stale_generation or result_conflict with explicit stale-generation detail (API should consistently prefer stale_generation when older identity is established).
6. Query result, output bytes, generation, job status and events: B remains sole authority, A rejected, zero incorrect results. Repeat A's rejection request ID and verify no duplicate durable rejection event.

Do not seed generation directly to 4 and claim the generation monotonicity mechanism was tested. Fixture may construct the partition set, but committed attempts must be real.

## Additional race/proof checks

Hold publication after job lock, start cancellation and observe it blocked. Release publication and verify the documented winner. Reverse lock order winner in another test. Abort the initial winner to verify waiting transaction rechecks current state. Hold API transaction before locks past the lease deadline to catch `now()` misuse. Validate the exact boundary `t == lease_expires_at` is invalid through a controlled clock/predicate test and a SQL boundary assertion; do not depend on hitting equality by real sleeps.

Run bounded seeded histories combining claim, renew, failure, expiry, publish and cancel. Compare every settled operation with a small independent reference state machine; continuously query invariant violations. Record seed and schedule on failure. This supplements the explicit races, not replaces them with random load.

## Acceptance gates

All listed correctness scenarios pass, invariants return zero violations, and actual output matches an independent oracle. Repeat race suite 100 schedules/seeds in CI's extended lane; ordinary PR lane uses deterministic core cases. Numeric throughput is not a correctness gate. A test failure blocks benchmark claims. Record dependency digests, OS/container versions, test seed, trace and exact commit for every published result.
