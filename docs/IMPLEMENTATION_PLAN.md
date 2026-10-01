# Implementation sequence and review gates

This package contains specifications only. Do not start application code until the contract is accepted for implementation. The first implementation milestone is a small executable vertical slice; fault tolerance is then added through gated milestones. Never call an intermediate milestone the complete V1.

## Planned repository structure

```text
relay/
  README.md
  pyproject.toml
  dependency-lockfile
  .gitignore
  .env.example
  compose.yaml
  Dockerfile
  docs/
    SPEC.md
    INVARIANTS.md
    STATE_MACHINES.md
    DATABASE.md
    FAILURE_MODEL.md
    API.md
    TEST_PLAN.md
    BENCHMARK_PLAN.md
    IMPLEMENTATION_PLAN.md
    decisions/
  src/relay/
    api/
    domain/
    db/
    control/          # all transactional transitions
    artifacts/        # import, reservation, gateway, version verification
    worker/           # session supervisor and task subprocess
    recovery/
    workloads/
    observability/
  migrations/
  tests/
    unit/
    integration/
    concurrency/
    faults/
    storage_contract/
  experiments/
    configs/
    harness/
    oracle/
    reports/          # small measured summaries only
  scripts/
```

Only docs and repository hygiene are included now. No placeholder application modules that imply implementation exists. This specification checkout may be initialized in Git immediately. A remote private repository must be created/pushed during M0 when the intended account and access are available; do not claim a remote backup without push verification.

## Sequential milestones

| Milestone | Implement | Exit evidence / claim allowed |
|---|---|---|
| M0 — contract and dependency gate | Review docs, create private remote, lock versions/digests, Compose DB/store, verify storage capabilities | Conditional create, exact-version read, readback SHA and runtime delete-denial pass. Contract amendments recorded. No runtime guarantee claimed |
| M1 — smallest useful slice | Migrations/core tables, immutable inputs and manifest validation, submit/status, one worker claim, reference transform, reserve/upload/verify, fenced completion, results | T01, basic T05/T17/T19/T21/T22 pass with real DB/store; one submitted job actually returns correct accepted output. No crash recovery claim yet |
| M2 — concurrent ownership | Worker sessions and auth, multiple processes, claim receipts, lease renewals, hard deadline, DB guards/events and scheduler tickets | T06/T12/T16/T18/T20 pass; contention does not duplicate ownership; leases reject expired publication even before reaper exists |
| M3 — recovery and fencing | Recovery loop, expiry, deterministic backoff, bounded retries, unknown-commit reconciliation | T02–T04/T09–T11/T23/T26 pass, including exact 4→5 trace. Claim recoverable crash/lease behavior only now |
| M4 — cancellation and adversarial lifecycle | Synchronous cancel, failure policy, drain/stop, poison/hang handling, restart recovery | T07/T08/T14/T15/T24/T25 pass; every documented failure has observed outcome |
| M5 — evidence harness and operational view | All deterministic barriers, scripted schedules, event/metric export, minimal CLI/status view, complete fault matrix | Entire test plan plus seeded state-machine histories pass; durable metrics reconciled to DB counts |
| M6 — preregistered measurements | Pilot resource check, freeze amendment if required, execute full benchmark matrix, independent oracle validation | Raw runs and honest report; zero correctness violations; no hidden failed runs |
| M7 — adversarial review and release | Review lock paths, SQL predicates, role permissions, storage assumptions, docs/API drift, reproducibility from clean checkout | Clean Compose reproduction, pinned evidence commit, limitations documented; only then GitHub/resume claims |

M1 is intentionally useful but incomplete: it already separates immutable upload from authoritative publication so later milestones do not require undoing an unsafe output model. It can allocate leases but has no automatic recovery service until M3. M2 must not relax the safety predicate in order to make happy-path tests easier.

## Review checklist tied to actual risks

- Every mutating path uses the common lock order and no external I/O while holding state locks.
- Time is sampled after the last potentially blocking lock, not when a transaction starts.
- Renew and complete require both current generation and valid lease; neither telemetry nor upload extends ownership.
- Successful retries reconcile durable identity, including unknown commit outcomes.
- Accepted metadata cannot be changed via API, role permissions or accidental UPSERT.
- Cancellation retains earlier results, stops new acceptance, and never pretends to stop remote CPU immediately.
- Tests operate across independent DB connections and worker processes; state predicates are not tested only with mocks.
- Benchmark results name their scope and limitations, especially serialized scheduler and per-job transactions.

## Git and artifact hygiene

Commit each passing milestone and its tests. Preserve failing experiment traces outside Git with small checksums/manifests committed as appropriate. Ignore `.env`, credentials, virtual environments, Python/test caches, local databases, object-store volumes, generated input/output data, huge traces and benchmark caches. `.env.example` contains names and safe placeholders only. Keep remote private initially; publishing or changing visibility is a separate action. Use explicit working-directory selection at the start of any future PowerShell instructions.

## Decisions frozen now

Single PostgreSQL authority; per-job transaction serialization; fair claim tickets with one scheduler row; one active attempt/session; lease plus unconditional attempt deadline; no renewal after expiry; one immutable output/attempt; verified version-pinned artifacts; one permanent acceptance/partition; drain remaining work after failure; synchronous logical cancellation; no automatic orphan GC; no in-place job rerun; no distributed global reduce.

## Remaining implementation checks

1. Select/pin a local object-store build only after conditional-write/version/permission tests. Failure blocks M0 rather than weakening artifact guarantees.
2. Verify 4,096-partition cancellation and descriptor bounds on actual hardware. If timeouts make the bound unusable, reduce the documented cap in a contract amendment before release; do not make partial cancellation observable.
3. Freeze dataset size after resource-only pilot, before comparative measurements.
4. Supply the intended private Git remote during M0. This document package alone is not evidence of a pushed remote or implemented system.

No unresolved correctness decision is delegated to the implementation agent. If a constraint proves infeasible, return with a specific counterexample and proposed contract amendment rather than silently removing it.
