# Failure behavior and externally visible outcomes

Safety scope: crash-stop/crash-recovery workers and control plane, message delay/loss/duplication, temporary DB/store unavailability and detected artifact corruption. Not Byzantine execution, storage administrator mutation, split-brain DB or loss of durable volumes.

| Failure | Durable transition / recovery | Externally observable outcome |
|---|---|---|
| Crash immediately after claim, before execution | ACTIVE eventually EXPIRED; READY with backoff or FAILED at cap | Attempt visible with expiry; new generation only on next claim |
| Crash during execution | Same; local partial file has no authority | Job continues after reassignment; recomputation measured |
| Freeze beyond lease | Renew/publish predicates reject even before recovery scan | 409 lease_expired; later generation may execute |
| Old worker wakes after reassignment | Identity/generation mismatch | 409 stale_generation; newer output unchanged |
| Heartbeat loss | Telemetry may become SUSPECT; lost attempt renew causes expiry | Suspect does not immediately revoke an otherwise live lease |
| Delayed heartbeat/renew | Worker heartbeat can update telemetry only with new sequence; late renew fails | 409 lease_expired for renewal; no resurrection |
| Duplicate heartbeat | Same/lower seq does not advance last_seen_at | 200 ignored/current telemetry; no lease change |
| Duplicate completion | Exact accepted identity replay | 200 same accepted result, no extra success event or count |
| Duplicate completion with another artifact/hash | Existing acceptance retained | 409 result_conflict |
| Upload succeeded; publication request never arrived | VERIFIED orphan; attempt remains ACTIVE until completion/expiry | Retry may publish if still eligible; otherwise 409 and no new authority |
| DB commit succeeded; completion response lost | Result already durable | Repeat/GET returns accepted identity even after lease expiry or job cancellation |
| DB failure before or during publication | Rollback if known; otherwise outcome unknown until reconciliation | 503 outcome_unknown when appropriate; inspect/retry exact identity |
| Repeated fail request / duplicate retry pressure | Failure receipt/terminal attempt prevents second transition | Same recorded disposition or conflict; no extra generation |
| Upload fails partway | No VERIFIED artifact; reserved key can be reconciled/retried | Retry upload while lease valid; eventual expiry if no progress |
| Wrong hash/schema before publication | Artifact REJECTED, no accepted result | 422 integrity_error; classify failure, bounded retry if transient transport cause |
| Corruption detected after acceptance | Append RESULT_INTEGRITY_ERROR incident; accepted row unchanged | Result download fails integrity check; job historic execution status remains SUCCEEDED with integrity incident exposed |
| Poison partition | Deterministic error fails immediately; retryable errors consume finite budget | Partition FAILED; job drains remaining partitions then FAILED |
| Retry exhaustion | Last attempt terminal and partition FAILED | max_attempts never exceeded; re-run needs a new job |
| Cancel before claim | Job and READY partitions CANCELLED | No claims for job; zero accepted outputs |
| Cancel during execution | ACTIVE attempt CANCELLED | Best-effort worker stops at next poll; renew/complete reject; CPU may continue temporarily |
| Cancel after artifact creation | Artifact retained, no new publication | Job CANCELLED; orphan output is not included in result manifest |
| Cancel races publication | Common job lock decides ordering | Earlier committed publication retained; cancel-first rejects publication; last-partition success-first makes cancel conflict |
| Worker restart | New boot/session; previous lease untouched | Old attempt expires; new session may claim other work |
| API restart | No authoritative in-memory state | Receipts/state survive; uploads reconcile; workers retry using same keys |
| Recovery restart | Rescan DB; conditional transitions idempotent | Delayed reassignment, no lost durable work |
| DB unavailable | No claims, renewals or new acceptance | 503; workers stop publishing assumptions; after recovery live clock may have expired leases |
| Store unavailable | Execution/upload/read cannot finish | Retry within attempt deadline; no false success; accepted manifest still queryable |
| DB host clock jumps | Forward: early expiry; backward: delayed expiry | No strict real-time expiry promise; generation/result safety unchanged |
| Disk full | Transaction or object write fails | No success response without committed acceptance; explicit capacity error |
| Durable DB/object volume lost | Outside recovery guarantee | Data-loss incident; no claim of automatic recovery from worker retry |

## Operational consequences

A missing response is not a negative acknowledgment. Clients must reconcile identity before deciding a request failed. Error payloads distinguish known rejection, retryable unavailability and unknown commit outcome. Workers may continue wasting CPU after lease loss; only publication is authoritative. Lease loss must terminate the child workload best-effort, and a supervisor heartbeat must not extend leases forever for a stuck task: hard_deadline_at is unconditional.

Accepted bytes are verified on download. Readback/schema verification detects corruption, not a semantically incorrect result produced by a buggy trusted workload. Independent reference-oracle testing validates workload correctness. No system can derive semantic correctness from a hash.

## Risk register

| Risk | Impact | Mitigation / evidence / owner milestone |
|---|---|---|
| Artifact store compatibility differs from S3 | Broken byte immutability | Conditional-write/version/readback tests block M0; switch local backend if unsupported |
| Job row and scheduler serialization | Throughput ceiling, cancellation contention | Short transactions, no I/O under locks, measure wait time at M6; document ceiling before redesign |
| Publication uses transaction-start clock | Expired attempt accepted | Fresh post-lock clock test T16; code-review gate M3 |
| Cross-table consistency omissions | Manifest points to wrong attempt | Composite FKs and deferred guards; invalid-DML tests M1/M3 |
| Supervisor renews stuck work forever | Lost liveness | Absolute hard deadline; poison/hang tests M4 |
| Lost claim response consumes work twice | Extra attempts / wasted work | Claim receipts and per-session ACTIVE uniqueness; T18 |
| Corruption after acceptance | Unreadable historic success | Pinned versions, no delete permissions, checksum reads, visible incident; no silent replacement |
| Unbounded orphan/event retention | Disk exhaustion | V1 size limits, capacity metrics, explicit operator cleanup only outside active run; GC deferred |
| Long cancellation transaction | Timeouts for large jobs | 4,096 partition cap, stress at limit before claiming it; no partial commit |
| Flaky timing tests | False confidence | Barriers and controlled lease expiry; small separate real-clock suite |
| Benchmark includes startup/cache artifacts | Misleading scaling claims | Predeclared timing boundary, repeats, cache policy and raw runs |
| Local laptop shared resource limits | Apparent regression at 8 workers | Fixed machine budget; report CPU throttling/I/O and serial baseline |
| Runtime/admin trust confused | Overstated security | Separate credentials; no Byzantine/multi-tenant claims |

Remaining decisions are implementation compatibility/resource checks, not unresolved safety policy: exact store build and library pins, measured feasible input size on the user's machine, and runtime timeout tuning after baseline data. Any change to locks, expiry, cancellation, retry count or immutability requires an explicit spec amendment before implementation.
