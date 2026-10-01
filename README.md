# Relay architecture contract — v1.0

Prepared 2 October 2026 from the two supplied Relay briefs. This checkout contains the architecture contract, accepted [M0 amendments](docs/decisions/2026-10-02-m0-contract-amendments.md), M0 infrastructure compatibility tests, and the M1A PostgreSQL persistence foundation. The Relay execution runtime and benchmarks remain unimplemented.

Start with [docs/SPEC.md](docs/SPEC.md), then follow its reading order. The nine documents include the architecture diagram, technology choices, schema and transactional pseudocode, state machines, failure outcomes, APIs, invariant-driven tests, reproducible fault/benchmark methodology, risk register and sequential milestones.

Key decisions: at-most-one accepted result per immutable partition; fresh DB-time fencing under locks; version-pinned artifacts; explicit cancellation ordering; bounded retries and absolute attempt lifetimes; no claims of universal exactly-once execution.

The existing origin is private. M0 and M1A validation evidence is recorded separately; remote synchronization must be verified against the actual Git HEAD.

## M0 prerequisites and setup

Use Python 3.12, Docker Desktop running Linux containers, Docker Compose v2, and network access to PyPI, Docker Hub, GitHub and the Go module proxy. The first MinIO build compiles source and takes longer than later cached builds. Services bind to localhost. This Compose project is for trusted local development.

The minimal dependencies are pinned in `pyproject.toml`; `uv.lock` fixes transitive versions and distribution hashes. uv itself is pinned to 0.12.21 in the bootstrap command. M1A adds SQLAlchemy 2 and Alembic to the retained M0 dependencies. FastAPI and PyArrow remain unimplemented later-milestone choices.

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

## Pinned candidate build

PostgreSQL is `18.6-trixie`, pinned by registry digest in Compose. MinIO is built locally as `relay-m0-minio:RELEASE.2025-10-15T17-29-55Z` from commit `9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a`, with its source archive SHA-256 enforced. Its Go builder and Alpine base are pinned by registry digests; upstream `go.mod`/`go.sum` and `-mod=readonly` fix the build dependencies. The mc setup binary is release `RELEASE.2025-08-13T08-35-41Z`, with its official asset SHA-256 enforced. Both services using this image are explicitly linux/amd64 for this Windows host.

The checked MinIO prebuilt registry tags were unavailable. Building the same candidate follows its [official release instructions](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z); no different storage backend is substituted. The locally built manifest digest is recorded as local evidence, not a published registry image that another machine can pull. See the evidence record for actually resolved identities.

To stop services while preserving development volumes:

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
docker compose down
```
