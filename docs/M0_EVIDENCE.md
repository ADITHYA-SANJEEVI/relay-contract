# M0 compatibility evidence — 2026-10-02

Result: **PASS** for the observed local infrastructure/storage gates. Relay's execution runtime remains unimplemented. Contract: V1 1.0 with accepted A1–A3. Starting Git HEAD: `47d432fd7b57f9cb107142189c1f1fdfa3e76c70`, branch `main`, clean starting tree, no remotes.

## Environment and identities

- Host Python: 3.12.10; project restricts Python to 3.12.
- Direct packages: boto3 1.43.107, psycopg/psycopg-binary 3.3.6, pytest 9.1.1, python-dotenv 1.2.4. `uv.lock` fixes all transitive versions and distribution hashes; uv bootstrap is 0.12.21. Versions were queried from official PyPI metadata before selection.
- Docker Desktop 4.44.0, Docker Engine 28.3.2 linux/amd64, Compose 2.39.1.
- PostgreSQL: `postgres:18.6-trixie@sha256:5a5a84b19854a9ffaa54082c166ff4ec27473a361e496e5ea167f298f2da9722`. Exact-reference image inspection returned `postgres@sha256:5a5a84b19854a9ffaa54082c166ff4ec27473a361e496e5ea167f298f2da9722`; server reported PostgreSQL 18.6.
- Candidate MinIO: locally built `relay-m0-minio:RELEASE.2025-10-15T17-29-55Z`. Docker image inspection returned local manifest/image ID `sha256:a2b76712120b57aec82cc5a4d2b9b87c71595510200430f4767e4e33d0b1a09d` and local RepoDigest `relay-m0-minio@sha256:a2b76712120b57aec82cc5a4d2b9b87c71595510200430f4767e4e33d0b1a09d`. This image has not been published; another machine must build it. `minio --version` reported release 2025-10-15T17-29-55Z, source commit `9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a`, Go 1.24.8 linux/amd64.
- Build inputs: source archive SHA-256 `45521908307306e925c98d629e1c17d78c8b72b6ee242b1bfb1409f7d8ee5841`; Go `1.24.8-alpine3.22@sha256:3d78beb141d98f42337f1252ecf2a5f20374109929a4c3f6817f9e4179cc0ae5`; Alpine `3.22.2@sha256:4b7ce07002c69e8f3d704a9c5d6fd3053be500b7f1c69fc0d80990c2ad8dd412`. Base digests were resolved from official Docker Hub metadata and used successfully by BuildKit; they are build-cache inputs, not separately tagged daemon images.
- Setup client mc: release 2025-08-13T08-35-41Z, binary SHA-256 `01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891`, from official GitHub release asset metadata. `mc --version` confirmed the release, commit `7394ce0dd2a80935aded936b09fa12cbb3cb8096`, Go 1.24.6 linux/amd64. The setup service reuses the same local MinIO image; no fourth service exists.

The MinIO Docker Hub tag API returned 404. Checked Quay manifests for MinIO server releases 2025-09-07 and 2025-04-22 and mc releases 2025-08-13 and 2025-04-16 returned `no such manifest`. The same MinIO candidate was built from source following its [official release instructions](https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z). No backend replacement or storage-contract weakening occurred. Conditional-create expected responses follow the [S3 conditional-write contract](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html); observed MinIO responses below establish this build's behavior.

## Service/setup evidence

`docker compose build minio` completed. `docker compose up -d --wait postgres minio` reported both services healthy. Both are localhost-bound with named durable volumes. `docker compose config --quiet` exited 0. `docker compose run --rm minio-setup` exited 0 on initial setup and repeat setup, printing only that versioning and the separate runtime policy were configured. Admin setup and runtime operations have distinct explicit credentials in ignored `.env`; no credentials are included in this evidence.

## PostgreSQL tests

All four tests are in `tests/infrastructure/test_postgres.py`:

| Test | Observed result |
|---|---|
| test_driver_and_server_major | psycopg 3.3.6 connection to database/user relay_m0; server_version_num=180006, major 18; Compose pinned image healthy |
| test_clock_timestamp_is_fresh_within_transaction | clock_timestamp advanced 0.067533 seconds while transaction_timestamp stayed identical; timezone-aware UTC timestamps |
| test_transactions_commit_and_rollback | Own uncommitted value 7 visible locally but second connection saw 0; commit exposed 7; deliberate rollback of 9 left 7 |
| test_two_connections_and_for_update_lock | Independent backend PIDs 678 and 679; held FOR UPDATE lock caused second connection SQLSTATE 55P03 under 200 ms lock_timeout; second connection acquired the lock after release |

Disposable tables are the sole added database schema. Tests use real PostgreSQL protocol/psycopg, not SQLite.

## Storage S1–S8

All eight tests are in `tests/storage_contract/test_storage.py`, named `test_s1_...` through `test_s8_...`. Each result is PASS:

| Gate | Observed result |
|---|---|
| S1 versioning | Admin GetBucketVersioning returned Status=Enabled. Runtime conditional PutObject returned 200 and opaque VersionId `e4a77365-b336-42f5-9450-d6626c33d6cc`; exact read returned original bytes |
| S2 conditional create | Initial PutObject with If-None-Match:* returned 200. Conflicting create returned HTTP 412, code PreconditionFailed, message `At least one of the pre-conditions you specified did not hold`; original version/bytes retained and admin version listing contained exactly one version |
| S3 explicit version | Runtime original VersionId `a641ed53-1e66-4efb-83fe-94bf6bc998c8`; trusted admin deliberately wrote a newer probe version `8ff45cb4-3994-4b8f-834c-1bc26360c7e6`. Runtime exact-version GET distinguished both byte sequences and returned the original bytes for the older ID. Admin write is solely a version-addressing probe, not a runtime-permission substitute |
| S4 SHA-256 | 262144 actual readback bytes hashed to `2312394bd99545d9de131c24efb781e765ac1aec243f2ed9347597a793a415e9`, matching expected SHA-256; ETag unused |
| S5 immutable identity | Two concurrent runtime conditional creates produced exactly one 200 and one 412 PreconditionFailed. Identical, conflicting and repeated conditional writes all returned 412; exact original bytes unchanged; exactly one version and no delete marker |
| S6 runtime delete denial | Runtime DeleteObject with exact VersionId and without VersionId both returned HTTP 403, AccessDenied, message `Access Denied.`; exact-version read still returned original bytes; one version and no delete marker |
| S7 separation | Actual client signer keys matched distinct configured identities. Admin versioning read allowed; runtime attempt to suspend versioning returned 403 AccessDenied. Versioning remained Enabled; runtime create/read succeeded with 200; no admin fallback |
| S8 reply loss/retry | Real PutObject succeeded with 200, then test discarded its reply at the SDK boundary. Repeated conditional write returned 412 PreconditionFailed; runtime HEAD discovered the opaque version, exact GET and SHA-256 matched original bytes, and admin listing showed one version |

## Verification commands and results

PowerShell commands used for verification:

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
.\.venv\Scripts\python.exe -m compileall -q scripts tests
.\.venv\Scripts\python.exe -m pytest --collect-only -q
.\.venv\Scripts\uv.exe lock --check --offline --cache-dir .cache/uv
.\.venv\Scripts\python.exe -m pytest tests/infrastructure tests/storage_contract -v -s --maxfail=1
git diff --check
```

Compilation exited 0; collection found 12 tests; lock check resolved 19 entries (project plus 18 dependency distributions). Initial full real-service suite: 12 passed in 2.96 seconds. After strengthening S3 to distinguish older/latest versions: 12 passed in 3.37 seconds. Final full suite after diff/hygiene inspection: 12 passed in 2.74 seconds, 0 failed, 0 skipped, 0 xfailed, no pytest warnings. The table above records the second run; generated version IDs and backend PIDs naturally vary on reruns.

Credential-value scan of all tracked and unignored candidate files found zero matches against the actual generated credentials. No `.env`, virtual environment, cache, object-store or PostgreSQL volume data was in the candidate source set. `.gitattributes` forces LF for setup shell scripts on Windows. Git's LF→CRLF notices for other text files are checkout normalization, not semantic test warnings.

## Observed limitations and claim boundary

MinIO logged that single-host failure makes its single-drive data unavailable. This local compatibility gate does not establish redundant storage or volume-loss recovery. PostgreSQL's initial temporary-server shutdown was part of successful initialization; the lock-timeout ERROR was deliberately generated by the locking test. No unexplained service/test error remained.

The sandboxed GitHub authentication check initially reported an invalid token. Rechecking with network access succeeded; both `gh auth status` and `gh api user` established account `ADITHYA-SANJEEVI`. Inspection of all 16 listed repositories found zero Relay-name matches. The authorized private repository `https://github.com/ADITHYA-SANJEEVI/relay-contract` was created and configured as origin. Merely creating a remote does not prove a backup: final delivery must separately report push verification against the committed local HEAD.

M0 establishes the documented amendments and the observed pinned real-service infrastructure/storage properties only. Job submission/execution, Relay schema/migrations, workers, claims, leases, renewal, retry/recovery, generation/publication fencing, cancellation, production artifact reconciliation, workload/Parquet validation and benchmarks remain unimplemented. Reply loss is injected at the SDK response boundary, not by a real network outage. Runtime writes are conditional under the trusted gateway contract; malicious/admin mutation is outside that contract.
