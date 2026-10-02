# Relay architecture contract — v1.0

Prepared 2 October 2026 from the two supplied Relay briefs. This checkout contains the architecture contract, accepted [M0 amendments](docs/decisions/2026-10-02-m0-contract-amendments.md), M0 infrastructure gates, M1A persistence, M1B verified artifacts, M1C fenced publication, M2 concurrent ownership/renewal and M3 recovery, bounded retries and generation fencing. Cancellation and benchmarks remain unimplemented.

Start with [docs/SPEC.md](docs/SPEC.md), then follow its reading order. The nine documents include the architecture diagram, technology choices, schema and transactional pseudocode, state machines, failure outcomes, APIs, invariant-driven tests, reproducible fault/benchmark methodology, risk register and sequential milestones.

Key decisions: at-most-one accepted result per immutable partition; fresh DB-time fencing under locks; version-pinned artifacts; explicit cancellation ordering; bounded retries and absolute attempt lifetimes; no claims of universal exactly-once execution.

The existing origin is private. Milestone validation evidence is recorded separately; remote synchronization must be verified against the actual Git HEAD.

## M0 prerequisites and setup

Use Python 3.12, Docker Desktop running Linux containers, Docker Compose v2, and network access to PyPI, Docker Hub, GitHub and the Go module proxy. The first MinIO build compiles source and takes longer than later cached builds. Services bind to localhost. This Compose project is for trusted local development.

The minimal dependencies are pinned in `pyproject.toml`; `uv.lock` fixes transitive versions and distribution hashes. uv itself is pinned to 0.12.21 in the bootstrap command. M1A adds SQLAlchemy 2 and Alembic; M1B adds FastAPI, uvicorn, PyArrow and HTTPX. Earlier package versions remain retained.

Run in PowerShell from the detected checkout:

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install uv==0.12.21
.\.venv\Scripts\uv.exe sync --locked --cache-dir .cache/uv
.\.venv\Scripts\python.exe scripts/init_env.py
docker compose build minio
```

Check each command succeeds before continuing. `init_env.py` creates ignored `.env` with random local values and refuses to overwrite an existing file. `.env.example` contains safe placeholders only. On subsequent runs retain the existing `.env`; do not rerun the initializer. Ports and bucket are configurable there. Keep the PostgreSQL password consistent with its existing durable volume.

Start services, then configure the versioned bucket and distinct runtime user:

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
docker compose up -d --wait postgres minio
docker compose run --rm minio-setup
docker compose ps
```

The setup container uses only admin credentials to create/configure the bucket, enable versioning, create the runtime user and attach policy. The runtime user receives only PutObject, GetObject and GetObjectVersion on this bucket, with explicit denial of DeleteObject and DeleteObjectVersion. Every tested gateway write uses `If-None-Match: *`; unconditional writes are outside the specified trusted gateway protocol. No application gateway is implemented by M0.

Named Docker volumes retain PostgreSQL and object-store data outside the checkout. Test objects use fresh canonical-shaped keys and remain retained; M0 adds no runtime cleanup or GC. Disposable database test tables are dropped after each test.

## Run the M0 gates

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
.\.venv\Scripts\uv.exe lock --check --offline --cache-dir .cache/uv
.\.venv\Scripts\python.exe -m pytest tests/infrastructure tests/storage_contract -v -s --maxfail=1
```

Tests first require the actual pinned Compose services to be healthy. They connect with psycopg 3 and use explicitly configured admin/runtime S3 clients without credential fallback or automatic SDK retries. Missing configuration, unavailable services, unexpected responses or mismatched bytes fail rather than skip. Stop M0 on any safety-relevant storage failure and obtain architecture review before replacing the backend. Do not begin M1 on a failed gate.

The PostgreSQL tests check server major 18, fresh `clock_timestamp()`, commit/rollback visibility, distinct backend connections and real `FOR UPDATE` contention. S1–S8 check API-reported versioning, create-only requests, opaque explicit-version reads, SHA-256 over actual readback, concurrent/repeated conflicting creates, runtime deletion denial, credential separation and reply-loss/retry behavior. Reply loss is injected after a real successful write at the SDK response boundary; this is not a network-partition or full artifact-reconciliation test. Payloads are opaque test bytes, not a Parquet workload.

M0 can establish reproducible infrastructure and the tested storage compatibility properties. It does not establish fault-tolerant execution, workers, claims, leases, retries, recovery, generation/publication fencing, cancellation correctness, exactly-once behavior, benchmark performance or production readiness. Those remain the sequential milestones in [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md). Observed validation is recorded in [M0_EVIDENCE.md](docs/M0_EVIDENCE.md).

## M1A persistence setup and gates

After M0 is green, run these commands, checking each exit status:

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
.\.venv\Scripts\uv.exe sync --locked --cache-dir .cache/uv
.\.venv\Scripts\python.exe scripts/init_db.py
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m pytest tests/persistence -v -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/infrastructure tests/storage_contract -v -s --maxfail=1
```

`init_db.py` uses the existing local infrastructure authority to create the separate `relay` database and `relay_runtime` login. It adds a random runtime password to ignored `.env` when needed, rejects an existing privileged runtime role, and is safe to repeat on this local setup. The retained `relay_m0` database and Docker volumes are preserved. Migration credentials are `relay_m0`; application connections default to `relay_runtime` with no admin fallback. Bootstrap must precede migration because the migration grants privileges to that role.

Alembic is the deployed DDL authority; runtime startup never calls `metadata.create_all()`. The initial migration uses explicit reviewed SQL, adds the circular latest-attempt FK after both tables exist, and seeds scheduler `(1,1)`. Persistence tests apply Alembic to fresh UUID-named databases on the actual Compose PostgreSQL service. Negative writes authenticate as the runtime login; the migration-owner history test is labeled separately. Downgrade/upgrade testing drops only its own disposable database. Do not downgrade the retained application database merely to rerun tests.

`src/relay/db` contains explicit Core metadata, psycopg engine configuration, explicit session/transaction construction, and the documented lock order. pytest and Alembic configure the `src` import path. The default engine sets READ COMMITTED, synchronous commit, a 2s lock timeout and 5s statement/idle-transaction timeouts. Future services must explicitly lock rows in the contract order and sample fresh DB time afterward. Deferred triggers check transaction state; they do not authenticate requests, enforce the live lease predicate or serialize concurrent operations. See [M1A_EVIDENCE.md](docs/M1A_EVIDENCE.md) for observed constraint evidence and remaining obligations.

## M1B / M1C local API and worker

After the regression gates pass, configure local API tokens, migrate and start the API in a terminal:

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
.\.venv\Scripts\uv.exe sync --locked --cache-dir .cache/uv
.\.venv\Scripts\python.exe scripts/init_api_env.py
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe scripts/serve.py --port 8000
```

The API binds only `127.0.0.1`. `/health/live` checks process liveness; `/health/ready` checks the runtime DB connection, revision `0002_readiness` via a read-only view, and store authentication/reachability. The M0 gates remain the capability checks for versioning/conditional creation/deletion denial. The view grants no direct runtime access to Alembic's table and changes no existing M1A guard or DML privilege. API configuration retains only runtime database/store credentials and the two API tokens. `init_api_env.py` adds missing random tokens to ignored `.env` and preserves existing ones.

Operator HTTP operations use `Authorization: Bearer <local operator token>`. Registration uses the distinct bootstrap token. After registration, a worker authenticates with its own client-held secret and `X-Worker-Session`. Neither secret appears in responses or stored plaintext. Request bodies reject unknown fields; bigint values use decimal strings. See [API.md](docs/API.md) for submission shape and [REFERENCE_WORKLOAD.md](docs/REFERENCE_WORKLOAD.md) for exact schemas/rules. Input execution format is canonical Parquet; no CSV importer is implemented.

Once a verified input and job are submitted, run one worker from another terminal. Set `RELAY_WORKER_BOOTSTRAP_TOKEN` in that terminal to the configured bootstrap credential without putting it in command arguments or logs:

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
.\.venv\Scripts\python.exe scripts/run_worker.py --base-url http://127.0.0.1:8000 --polls 1
```

The default worker creates a fresh boot UUID/secret, registers, claims, downloads assigned slices, executes in a separate child, reserves/uploads an output and exits at VERIFIED. A supervisor thread renews independently using monotonic timers, normally every 10 seconds; shorter lease policies advertise one third of their lease duration. Heartbeat telemetry remains separate. The child receives local task files and OS essentials only, without API/session/database/store credentials. The worker never reads `.env`; the launcher strips ambient infrastructure/operator credentials. Its JSON result reports `VERIFIED_UNACCEPTED`, supervisor/child identities, renewal acknowledgements, hash and counters. No work yields `NO_WORK`. Current ownership is inspected before every child starts, including claim receipt replay. Uncertain renewal responses retry the same sequence with a conservative local deadline. M3 retries uncertain register/claim/reserve/upload/complete requests up to three sends of the same identity; completion also inspects GET attempt. No replacement identity is created for a lost response. Exhausted uncertainty exits explicitly; recovery and a later fresh worker poll handle attempt reassignment.

Endpoints include live/ready, input reserve/upload/read, job submit/read/partitions/events/results, worker register/claim/heartbeat/drain/stop, attempt read/renew/complete/fail, assigned input-slice read and artifact reserve/upload/read. A VERIFIED artifact alone leaves its attempt ACTIVE and partition/job RUNNING, with `complete=false` and zero accepted results. Cancellation remains absent. Drain denies new claims while allowing existing work; stop requires no ACTIVE attempt, including expired but unsettled attempts. Process exit does not automatically mark STOPPED.

For one full M1C execution through acceptance, use:

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
.\.venv\Scripts\python.exe scripts/run_worker.py --base-url http://127.0.0.1:8000 --polls 1 --complete
```

After VERIFIED, this mode sends `POST /v1/attempts/{id}/complete` and exits only after observing the matching accepted identity (`phase=ACCEPTED`). Each invocation is a fresh session and processes one partition. Multiple invocations may run concurrently. Renewals maintain the lease only while strict current ownership remains live and never move the immutable hard deadline. Definite renewal loss terminates the workload child best-effort and prevents publication. On Windows, termination targets the launched child's process tree to cover the venv launcher; it does not terminate unrelated workers.

Completion requires `{request_id,job_id,partition_id,generation,artifact_id,artifact_uri,sha256}`. Use the `artifact_uri` returned by verification: `s3://<registered-bucket>/<registered-key>?versionId=<URL-encoded-opaque-version>`. This string identifies registered metadata; the API never fetches caller-provided URLs. Request IDs are bounded nonempty strings of at most 128 characters. New acceptance uses a full conditional SQL ownership gate after job → partition → attempt → artifact locks and a fresh DB clock sample. Success returns 201; exact historical replay returns 200 with unchanged `accepted_at`, even after expiry. A known rejection is durable per worker/request ID; a corrected request uses a new ID. A 503 can represent unknown commit outcome, so reconcile through the same completion or result reads.

`GET /v1/jobs/{id}/results` returns accepted manifests in ordinal order, with pagination, status, count and complete flag. It verifies each page's exact pinned versions outside the read-only DB snapshot. Operator `GET /v1/artifacts/{id}/content` serves accepted content only; the owning worker can also read its VERIFIED output. Bytes are verified before streaming, with `X-SHA256` and `X-Object-Version` headers. Missing/corrupt pinned versions return explicit `integrity_failure` without substitution, metadata replacement or recomputation.

Run M1B and regressions separately, checking each exit status:

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration -v -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/publication -v -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/concurrency -v -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/faults -v -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/persistence -v -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/infrastructure tests/storage_contract -v -s --maxfail=1
```

Integration tests launch a real API process and credential-restricted independent workers, use disposable UUID-named databases on Compose PostgreSQL, and retain immutable test objects in MinIO. Harness temporary credentials/logs are confined to ignored workspace cache children and removed after their processes exit. The storage observer uses real gateway calls and checks both pool state and PostgreSQL transaction state; it does not mock S3. [M1B_EVIDENCE.md](docs/M1B_EVIDENCE.md) records the previous pass. [M1C_EVIDENCE.md](docs/M1C_EVIDENCE.md) records full three-partition T01, basic T05 completion concurrency, T26 and rejection/replay evidence. Test-only SQL triggers/barriers exist solely in disposable databases; no production fault-control endpoint is installed. The missing-version test deliberately deletes only its own fixture's pinned version using the trusted storage administrator to establish explicit integrity failure.

[M2_EVIDENCE.md](docs/M2_EVIDENCE.md) records the accepted previous-pass claim contention, sequence/deadline, session restart and supervisor evidence. Its expired attempts remained unsettled at that milestone. Test controls live under `tests/concurrency` and `tests/faults`; production CLI/API expose no fault-control endpoint. Hard-deadline tests wait through the real 60-second minimum lifetime. Correctness timing is not a throughput benchmark.

## M3 recovery and failure

Run the independent recovery process alongside the API:

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
.\.venv\Scripts\python.exe scripts/run_recovery.py --env-file .env
```

Recovery retains only `POSTGRES_RUNTIME_PASSWORD`, `POSTGRES_PORT` and `POSTGRES_DATABASE` from that file. A separate ignored file containing just those three fields also works. It needs no worker/API/store/admin credential. Default polling is 1 second with 100 unlocked candidates; `--once` performs one batch and exits. Multiple processes can safely run concurrently. Each candidate gets its own job → partition → attempt transaction and a fresh DB-time recheck after locks. An expired current ACTIVE attempt becomes EXPIRED; retry budget schedules READY at `finished_at + min(2^(generation-1),30)` seconds, or FAILED at exhaustion. Only a later eligible committed claim creates the next generation. Failed partitions drain other READY/RUNNING work before the job becomes FAILED.

`POST /v1/attempts/{id}/fail` takes `{job_id,partition_id,generation,code,detail}` under the owner's session credential. M3 accepts retryable `worker_crash`, `store_transient`, `transport_error`; nonretryable `input_invalid`, `schema_mismatch`, `workload_validation`, `integer_overflow`. Unknown codes/fields, a caller retryability flag or invalid detail reject 422. Detail is a JSON object bounded to 4 KiB of canonical UTF-8. An exact failure repeat returns its original disposition even after another generation claims, without rescheduling or another event. Changed terminal failure conflicts. Expired fresh failure leaves expiry settlement to recovery. Worker computation exceptions still exit and recover through expiry unless explicitly reported by the owner.

Run M3 and all earlier gates as separate invocations (API-heavy suites serially on this Windows host):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/faults -q -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/concurrency -q -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/publication -q -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration -q -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/persistence -q --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/infrastructure tests/storage_contract -q --maxfail=1
```

[M3_EVIDENCE.md](docs/M3_EVIDENCE.md) records real OS crashes, competing recovery loops, retry caps, both race orderings and the exact ordinal-17 generation 1→5 history. Generation 4 produces VERIFIED artifact A and stops renewing before publication; recovery expires it, a distinct generation-5 worker publishes B, and A's repeated original completion is fenced as stale. VERIFIED orphans remain retained and unaccepted, with new attempt/artifact/key identities for later generations. Cancellation, GC, complete outage/restart coverage and benchmark claims remain later work.

## Pinned candidate build

PostgreSQL is `18.6-trixie`, pinned by registry digest in Compose. MinIO is built locally as `relay-m0-minio:RELEASE.2025-10-15T17-29-55Z` from commit `9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a`, with its source archive SHA-256 enforced. Its Go builder and Alpine base are pinned by registry digests; upstream `go.mod`/`go.sum` and `-mod=readonly` fix the build dependencies. The mc setup binary is release `RELEASE.2025-08-13T08-35-41Z`, with its official asset SHA-256 enforced. Both services using this image are explicitly linux/amd64 for this Windows host.

The checked MinIO prebuilt registry tags were unavailable. Building the same candidate follows its [official release instructions](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z); no different storage backend is substituted. The locally built manifest digest is recorded as local evidence, not a published registry image that another machine can pull. See the evidence record for actually resolved identities.

To stop services while preserving development volumes:

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
docker compose down
```
