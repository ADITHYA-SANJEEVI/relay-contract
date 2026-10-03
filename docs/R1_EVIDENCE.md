# Relay R1 backend operator visibility evidence

Observed on **3 October 2026 (IST)** in the existing Windows / Python 3.12.10
checkout, using real Compose PostgreSQL 18.6 and pinned M0 MinIO. R1 is an
additive read surface; no frontend Slice 2, R2, deployment, push, merge or tag.

## Identity and startup gate

- Branch: `r1/operator-visibility`.
- Starting SHA: `8aab14010b8e4f653fadb470c4a83b00dd3ab814`.
- Initial `git branch --show-current`, `git status --short` and
  `git rev-parse HEAD` matched the required branch/SHA and clean tree.
- Frozen frontend milestone: `relay-frontend-slice1-final`, resolving to
  `7083518def4cbef1d298a8a44382812b4735a615`; no tag was changed.
- Implementation SHA: `32300b74fad9a0255ec26e149bd4ef2027d79a60`
  (`Implement Relay R1 operator visibility`), recorded by this later evidence
  commit without self-reference.
- Evidence commit: the containing Git commit identifies this document; no
  self-referential ending SHA is embedded.

The product specification, frozen Slice 1 evidence, API/database/invariant/
failure/state-machine contracts, M3 evidence, SPEC, implementation/test plan,
reference workload and accepted M0 A1-A3 decisions were read alongside runtime,
schema, migration, gateway, frontend adapter/domain and failure-test code. The
earlier proposal package named in the product specification is absent from this
checkout and is not treated as accepted implemented architecture.

## Implemented capabilities and routes

All **16 routes are GET-only**, under the existing operator bearer authentication:

| Capability | Exact route paths under `/v1/operator` |
|---|---|
| BV01_JOBS_CATALOGUE | `/jobs`, `/jobs/{identity}` |
| BV03_PARTITION_HISTORY | `/jobs/{identity}/partitions`, `/partitions/{identity}`, `/partitions/{identity}/history` |
| BV04_ATTEMPT_DETAIL | `/attempts/{identity}` |
| BV05_ARTIFACT_METADATA | `/artifacts/{identity}`, `/artifacts/{identity}/verification` |
| BV06_RESULT_METADATA | `/jobs/{identity}/result-metadata` |
| BV07_FLEET_HISTORY | `/workers`, `/workers/{identity}`, `/workers/{identity}/attempts`, `/workers/{identity}/events` |
| BV08_TAIL_FILTER_EVENTS | `/jobs/{identity}/events` |
| BV09_DEFINITION | `/jobs/{identity}/definition` |
| BV12_OBSERVATION_CLOCK | `/capabilities`; DB observation fields on every operator read |

The authoritative route/parameter/schema/source/error/verification contract is
[OPERATOR_API.md](OPERATOR_API.md), linked from [API.md](API.md). OpenAPI was
generated locally and inspected: 16 operator paths, GET only, typed responses.
This inspection opened no service port and published no application.

Explicit typed frozen responses separate lifecycle, observed ownership, recorded
artifact metadata, accepted authority and explicit content verification. No ORM
or Core persistence rows are returned to clients. Bigints remain decimal strings.
The existing exact BV01/BV03/BV07 frontend IDs and product BV01-BV12 categories
are preserved. No frontend/shared type generation or integration was performed.

## Deferred and unsupported gaps

- **BV02_SUMMARY — DEFER:** no installation gauges/counters, query-window summary
  or KPI aggregation; the minimum investigation workflow uses scoped job facts.
- **BV10_BROWSER_AUTH — DEFER:** existing local operator bearer is reused. No
  cookie/session/pairing/RBAC/CSRF/CORS adapter or production-auth claim.
- **BV11_REPORTS_CONTROLLER — DEFER:** no evidence catalogue/import, report
  schema, benchmark results, local fault controller or shell/path proxy.
- **UNSUPPORTED BY CURRENT AUTHORITY MODEL:** durable heartbeat history, CPU
  progress/execution spans, online/crash certainty, global event order, complete
  artifact-verification event history and durable integrity-incident history.
  No additional capability IDs/state tables are invented for these gaps.

Capabilities reports AVAILABLE for the implemented route contracts and DEFERRED
for BV02/BV10/BV11, along with API and database revisions and existing auth mode.
Availability is an implementation fact, not a live-cluster health assertion.
Database failure remains a typed dependency error; existing health probes retain
their separate liveness/readiness semantics.

## Authority and verification evidence

Accepted authority comes only from the immutable `accepted_results` relation:
partition, attempt, generation, artifact, accepted_at and publication fingerprint.
No result row returns NONE, including a VERIFIED orphan. Latest generation,
SUCCEEDED attempt state, matching hashes and object existence do not establish
authority. Old attempt/artifact reads retain the actual partition authority and
separately indicate whether that inspected identity is accepted.

The R1 projection regression tests an older accepted generation alongside a
different current-generation observation, and a SUCCEEDED observation without
an accepted row, **without** inserting inconsistent persisted runtime state or
disabling guards. The current authority model normally prevents generation
advancement after terminal acceptance. The DTO does not assume equality to
recover result identity.

Metadata-only accepted manifests never touch object storage. Explicit verification
closes the metadata transaction before reading exact pinned/versioned bytes,
computes SHA-256/count and checks output Parquet schema. A newer object version
at the same key was created only by the trusted test fixture; the diagnostic
still verified the original committed version. Deleting only that fixture's
pinned version produced an explicit failed read while accepted metadata,
artifact metadata, job/partition state and manifest membership remained unchanged.
This follows the existing M1C trusted-admin corruption fixture; R1 offers no
deletion or repair action.

Seven diagnostic boundary cases supplement real-storage verification: checksum
mismatch, excess size, missing version, missing storage object, unreachable
endpoint, transport read error and invalid Parquet. All retain recorded accepted
authority independently of verification state. These controlled transport/parser
fixtures do not replace real PostgreSQL, MinIO, publication or fault coverage.
No semantic oracle certification is inferred from byte verification.

## History, events and workers

Partition history returns all recorded attempts (maximum ten under accepted
policy), descending generation with deterministic identity tie-breaker and
history_complete=true. It does not embed an unbounded event list; each attempt
links to its scoped event chronology. Larger malformed history rejects rather
than silently truncating. Current/latest attempt and accepted result are separate
relations. An ACTIVE row past deadline remains ACTIVE with a DEADLINE_PASSED
observation until real recovery commits EXPIRED.

Events use the persisted per-job sequence, bounded forward/backward pages,
partition/attempt scope checks, loaded range, retained frontier and explicit
continuation. Every delivered page is chronological, including tail pages.
Worker lifecycle events use their separate session sequence and expose no
invented actor/job/global ordering. Unknown or malformed diagnostic details are
bounded before Python parsing, type-allowlisted and omitted/flagged, with raw
failure detail and worker credential hashes excluded. Invalid bigint/Unicode
cursor inputs reject. Manual defensive checks also confirmed excessive JSON
depth and an unknown diagnostic code are suppressed.

Worker reads expose genuine session identity, durable REGISTERED/DRAINING/STOPPED
state, heartbeat fields and recorded ACTIVE assignment. FRESH/SUSPECT use the
existing 30-second DB-clock rule; STOPPED returns NOT_APPLICABLE. An expired but
unsettled ACTIVE assignment remains visible and does not imply usable ownership.
Participation is paged by attempt UUID across jobs; lifecycle is paged by seq.
Equal display names are distinct sessions. No heartbeat graph, CPU/host facts,
admin control or proven online/offline label is introduced.

## Actual runtime/failure scenarios

R1 tests reuse existing M1B/M1C/M3 real-service helpers and production transitions:

- **T04:** real claims G1-G5; each G1-G4 expired through production recovery,
  with lease shortening/eligibility advancement restricted to existing fixture
  controls. G4 retained its VERIFIED artifact; G5 alone accepted a distinct
  artifact with matching deterministic hash. Late G4 completion and exact replay
  returned stale_generation; one recorded rejection was correlated to G4's
  exact job/partition/attempt/request. Read history returned [5,4,3,2,1]. This
  R1 case uses partition ordinal 0; the unchanged M3 process suite additionally
  reproduces the actual ordinal-17 generation-4/5 worker/recovery scenario.
- **T09:** three real retryable failures exhausted a partition's budget. The job
  stayed RUNNING while healthy work drained, then FAILED with one of two outputs
  accepted, complete=false and all three failed attempts inspectable. No fourth
  target claim was available.
- **Expiry/recovery:** elapsed ACTIVE ownership remained observational until
  recovery; settled history and retry eligibility remained inspectable.
- **Duplicate compute/provenance:** old and new verified artifacts with matching
  hashes retained different identities; only G5 participated in authority.
- **Publication/integrity:** accepted manifests, pinned exact bytes, newer-version
  non-substitution and missing-version/mismatch failures remained independent.
- **M3/M2/M1C regression:** actual owned worker/recovery processes, races,
  publication rollback/replay, renewal and invariant suites were rerun unchanged.

No new core inconsistency was exposed in these runs. The product specification's
preexisting cancellation-guard/oracle-review notes are not resolved by R1 and
are not used to claim full V1 or general semantic workload validation.

## Database and query behavior

Every operator database response uses a DB-enforced READ ONLY, REPEATABLE READ
transaction with one as_of sample when its snapshot is acquired. A concurrent
real HTTP failure committed on an independent connection was invisible within
the existing operator snapshot and visible to the next read. Attempted DML in
an operator snapshot rejected with PostgreSQL SQLSTATE 25006.

All 16 routes were exercised around one accepted job and all **13 authoritative
tables** compared before/after; no row changed. Source AST review found no DML,
FOR UPDATE, upload or deletion calls in the operator modules. Metadata tests
made storage reads fail if attempted and still passed. A partition page of one
or three rows executed exactly six statements, including transaction setup and
clock; query count did not grow with row count. One-to-one joins and bounded
batch reads avoid N+1 round trips and Cartesian history joins. No denormalized
state, cache authority or event/receipt rewriting was added.

Migration `0003_operator_indexes` changes only four indexes:

1. jobs(created_at,id): stable descending catalogue keyset.
2. jobs(status,created_at,id): filtered catalogue keyset.
3. attempts(worker_session_id,id): historical participation beyond ACTIVE-only
   session uniqueness.
4. events(job_id,attempt_id,seq): correlated event pages, complementing the
   existing partition-event index and job-event primary key.

Real PostgreSQL EXPLAIN of the operator query shapes selected these access paths
with sequential scans disabled on small fixtures. This establishes index
eligibility, not scale/latency evidence. Persistence tests verified schema/index
parity, clean upgrade/downgrade/upgrade and unchanged guards/roles. Readiness now
requires this exact revision. Existing retained installation databases were not
migrated or settled during this pass; deployment requires the ordinary Alembic
upgrade before running the new API.

Definition reads are bounded by the existing 1 MiB submission descriptor,
4096 inputs/partitions and defensive slice probes. Normal growing lists are
keyset/sequence paged, maximum 500; no offset paging or silent first-100 history.
Every request/page has its own snapshot. Verification uses a later API UTC
checked_at after the DB transaction closes; no combined DB/store atomicity is
claimed. Existing DB/transport timeouts and 256 MiB output bounds are retained.

## Validation totals and environment

**PASS: 271 distinct backend test items** (21 R1 plus all 250 existing items).
All final gates passed with no failures, skips, xfails or pytest warnings.

| Gate | Passed | Duration |
|---|---:|---:|
| R1 `tests/operator_visibility` | 21 | 140.98s |
| M3 `tests/faults` | 29 | 385.46s |
| M2 `tests/concurrency` | 25 | 299.47s |
| M1C `tests/publication` | 25 | 174.04s |
| Backend `tests/unit` | 9 | 2.23s |
| Backend `tests/integration` | 28 | 164.30s |
| M1A `tests/persistence` | 122 | 21.56s |
| M0 `tests/infrastructure tests/storage_contract` | 12 | 3.15s |

The established suites are invoked serially against independently allocated
UUID-named migrated databases and localhost API processes. Services were already
healthy; no container recreation, volume deletion, dependency replacement or
SQLite substitute. Compose identity checked:

- PostgreSQL `postgres:18.6-trixie@sha256:5a5a84b19854a9ffaa54082c166ff4ec27473a361e496e5ea167f298f2da9722`.
- MinIO `relay-m0-minio:RELEASE.2025-10-15T17-29-55Z`.
- Windows, Python **3.12.10**, dependency pins in the unchanged uv.lock.

Commands (each pytest invocation is independent; unit and integration together
cover the established 37-item backend group):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/operator_visibility -q --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/faults -q --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/concurrency -q --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/publication -q --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/unit -q --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/integration -q --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/persistence -q --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/infrastructure tests/storage_contract -q --maxfail=1
.\.venv\Scripts\python.exe -m compileall -q src scripts tests
.\.venv\Scripts\uv.exe lock --check --offline --cache-dir .cache/uv
git diff --check
```

Compileall, unchanged offline dependency lock, whitespace, OpenAPI method/schema,
preservation and local-credential-byte scans passed. This backend has no
configured Ruff/Mypy/formatting gate; no new tool/dependency was invented.
Frontend validation was not rerun as a substitute for backend validation.

Development observations are excluded from passing totals: pytest initially
collided with the Python standard-library `operator` name when the new test
folder had that name; it was renamed to `operator_visibility`. A TestClient
deprecation was eliminated by using the repository's existing httpx ASGI
transport pattern, without suppressing warnings or adding a dependency. The
first R1 execution failed only a string timestamp assertion (`Z` vs `+00:00`);
the assertion now compares timezone-bearing datetime instants. The complete
21-item rerun passed. A standalone inspection script required the repository's
src path before import and then passed. No timing threshold, production predicate,
existing test, skip/xfail or safety assertion was weakened.

## Preservation and changed files

Pre-commit mechanical comparisons to the starting SHA show:

- No `frontend/**` or `docs/ui/**` modifications, fixtures or screenshot changes.
- No historical M0-M3 evidence rewrite.
- No control/publication/leases/settlement, recovery, worker or gateway change.
- No original schema columns, guards, triggers, grants or migrations changed.
- No dependency, lockfile, Compose, credentials, secret, cache, venv, generated
  input/output, binary or benchmark artifact staged.
- PostgreSQL authority, generations, lease ownership, retry/recovery, publication
  fingerprint/artifact identity, terminal states, stale fencing and event order
  retain their accepted meanings. Duplicate compute remains permitted.

Exact implementation files:

```text
docs/API.md
docs/OPERATOR_API.md
migrations/versions/0003_operator_indexes.py
src/relay/api/app.py
src/relay/db/schema.py
src/relay/operator/__init__.py
src/relay/operator/models.py
src/relay/operator/routes.py
src/relay/operator/service.py
tests/operator_visibility/__init__.py
tests/operator_visibility/conftest.py
tests/operator_visibility/test_visibility.py
```

The evidence commit adds only `docs/R1_EVIDENCE.md`. Existing source changes are
limited to mounting the operator router, operator-specific cache/error handling,
readiness revision and four additive metadata indexes.

## Frontend Slice 2 and R2 readiness / limitations

The frozen adapter can later integrate the real catalogue, complete history,
enriched snapshots, provenance, metadata-only manifests, worker reads and event
tail/filter contracts. It must map response envelopes and bigint strings,
preserve authority on failed verification, honor page/snapshot scopes and retain
capability gaps. BV10 remains an explicit browser-live connection prerequisite;
backend reads do not make the frozen frontend automatically live-integrated.
No frontend source/fixtures/shared types were changed.

R1 establishes tested local read visibility over M1-M3, not production deployment,
full V1, cancellation, general metrics, semantic oracle validity, durable incident
history, controller support, real-time streaming or installation-wide snapshot
consistency. Query access paths are tested on bounded fixtures; large-history/
installation capacity and repeated verification cost are unmeasured. Verification
may read a full bounded output and is explicit, never background polling.

R2 can use the read contracts to collect provenance after a separately scoped
benchmark/report methodology and unresolved prerequisites are approved. No R2
pilot, benchmark, release/deployment or throughput claim was started here.
Final working tree/commit identities are reported by Git and the final task
report. Push **NO**; merge **NO**; tag **NO**.
