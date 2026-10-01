# M1B execution evidence — VERIFIED and unaccepted

Observed on the accepted M1A checkout on 2 October 2026 local time. Starting `main` HEAD was `0215096c8508f7a1c449148796bdcc64bae87da6`, with a clean tree and existing private origin `ADITHYA-SANJEEVI/relay-contract`. The evidence below was captured from the M1B implementation before its final commit; the containing Git commit identifies the shipped code. This pass stops at VERIFIED. M1C and full T01 are not implemented.

## Baseline and environment

- Python 3.12.10; PostgreSQL 18.6 (`server_version_num=180006`); pinned M0 MinIO build, both Compose services healthy.
- Starting M0 suite: 12 passed in 3.17s.
- Starting M1A suite: 122 passed in 22.87s.
- Existing image identities, M0 tests, migration `0001_persistence`, schema guards and table privileges remain unchanged.
- Application writes authenticate as `relay_runtime`. API configuration excludes migration/admin credentials. Gateway uses only the existing non-admin S3 runtime identity, with no delete privilege. Worker environment contains OS essentials and the API bootstrap token; it receives no database/store/operator credentials and never reads `.env`.
- The API is one independent localhost Python/uvicorn process; PostgreSQL and MinIO remain Compose-backed. The artifact gateway is part of that API.

## Retained real-process trace

The retained trace was executed in the separate application database **`relay`**, not the M0 database or a fabricated in-memory state. A real HTTP API process imported canonical Parquet and submitted a finite manifest; an independent OS worker performed register → claim → download assigned slice → execute → reserve → upload → VERIFIED. API PID **16340**, worker PID **3560**. The worker completed in **1.516s** including registration, comfortably within the unchanged 30s initial lease.

| Identity | Observed value |
|---|---|
| Input | `3d4414f2-49f4-4845-b849-007bee2b7447` |
| Input version | `8f784257-8da4-4837-8140-5969080285c2` |
| Input SHA-256 | `132ca24278318c3c5d9cb008bd360e033a7b5fd257194751525c48c2ce34df96` |
| Input schema hash | `ef2d6cb7f2010dddeab02b7d5a471909d86bfa7254d270ed78ffb16efb06eb7e` |
| Input bytes/rows | 2,698 bytes / 20 rows |
| Job | `5dbe8a6b-ccaf-42a0-ab79-a190b7d04b4e` |
| Definition hash | `60876ef75ed3afa518965b15bd441912326ab20770d5472cad99324147fb7873` |
| Partition | `95e1923c-3d89-41d6-b28e-0f66553ad362`, ordinal 0, slice `[0,10)` |
| Other partition | Ordinal 1, slice `[10,20)`, remains READY |
| Worker session | `eb24d760-f8da-4b2e-ab26-643c1650dae4` |
| Attempt | `ce849793-0a80-4c7c-9928-2565952223bb`, generation 1 |
| Artifact | `90f7cf24-9044-421b-840b-987e3c25def6` |
| Artifact version | `d40bfd6e-fa64-4bb7-9da3-b187faa5b3a0` |
| Artifact SHA-256 | `bdcdf18e6dbf7189dc40796f307ad543108749fc73234514a0020f94ba174ffe` |
| Artifact bytes | 2,029 |

Canonical object key:

```text
jobs/5dbe8a6b-ccaf-42a0-ab79-a190b7d04b4e/partitions/0/attempt-1/90f7cf24-9044-421b-840b-987e3c25def6/output.parquet
```

DB timestamps were observed as UTC, corresponding to 2 October locally:

- claimed_at: `2026-10-01T23:36:04.088033+00:00`
- lease_expires_at: `2026-10-01T23:36:34.088033+00:00`
- hard_deadline_at: `2026-10-01T23:46:04.088033+00:00`
- artifact verified_at: `2026-10-01T23:36:04.545221+00:00`

The gateway pinned the actual opaque version and read that exact version. A subsequent independent runtime S3 GetObject addressed the same version, recomputed SHA-256 over returned bytes, parsed the output schema and compared decoded groups against the independent serial oracle for exactly the first ten input rows. All matched. Counters: 10 input rows, 8 valid, 2 invalid (`invalid_record_id=1`, `invalid_region=1`), 7 output groups. No global reduction is claimed. The generated input/output objects and application rows remain retained; API/worker processes exited after this run.

## Authority separation and events

Actual runtime-role PostgreSQL inspection after verification:

| Entity | Durable state |
|---|---|
| Artifact | VERIFIED |
| Attempt | ACTIVE, generation 1 |
| Claimed partition | RUNNING |
| Job | RUNNING |
| accepted_results for partition | **0** |

No success transition or accepted-result insertion exists in M1B application code. GET job reported `complete=false` and zero partial accepted results. GET attempt reported the verified artifact and `accepted_result=null`.

Observed per-job event order:

1. JOB_SUBMITTED
2. ATTEMPT_CLAIMED
3. PARTITION_RUNNING
4. JOB_RUNNING
5. ARTIFACT_RESERVED

Sequence allocation and corresponding mutations share each authoritative transaction. Verification locks only the artifact row after external I/O; it does not create a job success event or publication authority. The initial lease later expires without automatic settlement, as expected for M1B. Durable ACTIVE state after worker exit does not imply live ownership after the deadline.

## Transactions, locks and live ownership

- Input reservation uses the immutable natural import key/fingerprint. A duplicate-key race rolls back and reads the winner in a fresh transaction. Input metadata verification locks only the input row after storage/parsing.
- Submission validates bounds/contiguous ordinals/disjoint complete coverage before its authoritative transaction, locks scheduler, rechecks receipt and VERIFIED identities, then inserts job, all input/partition/slice relations, event and receipt and advances the ticket atomically. It satisfies unchanged creation_xid guards naturally. Definitions include materialized defaults and immutable input versions/hashes/size/schema/count.
- Registration locks only its worker domain; a workers-table SHARE ROW EXCLUSIVE lock serializes configured capacity checks. Exact retry returns the same binding; changed binding conflicts. Only credential hashes are stored. Capacity remains bounded to at most 32 configured sessions.
- Claim discovers candidates without ownership locks, then locks scheduler → selected job → lowest eligible partition → worker, rechecking under those locks. No SKIP LOCKED or Python mutex is used. One `clock_timestamp()` ownership sample follows the final worker lock. Generation/projection/ACTIVE attempt, 30s lease, immutable 600s hard deadline, job/partition state, fair ticket, events and receipt commit together.
- Reservation locks job → partition → attempt. One fresh `clock_timestamp()` sample follows the last authoritative lock and evaluates the entire canonical predicate, including exact job/partition/current generation/attempt binding, authenticated owner, ACTIVE state and strict lease/hard-deadline inequalities. Exact fingerprint retry returns one reservation; a changed fingerprint conflicts. No storage I/O occurs in this transaction.
- Gateway conditionally creates only the reserved key with `If-None-Match: *`, reconciles existing keys, reads the exact version, computes hash/count and parses Parquet entirely outside a state transaction. Only afterward does it lock the artifact and CAS RESERVED→VERIFIED. A verified retry preserves original metadata. Conflicting bytes cannot replace the object.
- Known server constraint/timeout aborts return no success and `not_committed`; a disconnect/uncertain commit returns 503 with `unknown`. Stable receipts/reservations support read/retry reconciliation. No new claim is fabricated on receipt replay.

## Test evidence

M1B tests use real HTTP processes, real PostgreSQL and real MinIO; no SQLite or mocked S3 correctness path. Integration databases are UUID-named disposable databases, preserving retained M0/application data and object versions. The separate-process precursor name explicitly avoids claiming full T01.

| Tests | Observed assertions |
|---|---|
| test_input_idempotency_pin_and_real_bytes | Same key/body→same ID; changed payload→409; VERIFIED exact version/hash/bytes; repeat retains one version |
| test_input_incorrect_hash_rejected / test_noncanonical_parquet_rejected | Wrong incoming hash→422 without object authority; wrong stored schema→422/REJECTED |
| test_storage_io_without_open_transaction_and_conditional_protocol | At real PutObject/GetObject callbacks, API pool had zero checked-out connections and PostgreSQL reported zero runtime transactions; conditional header and exact read version inspected |
| test_valid_manifest_submission_idempotency_and_rerun | All contiguous partitions/slices created; exact replay same ID; conflict 409; new key permits same definition |
| test_invalid_submission_leaves_no_partial_rows | Overlap/gap/ordinal/bounds/unsupported digest/unknown-field rejections leave zero job/manifest/event/receipt rows and unchanged scheduler |
| test_unverified_input_submission_rejected / test_empty_input_has_explicit_empty_partition | RESERVED input rejected; explicit empty slice accepted |
| test_submission_real_database_abort_rolls_back_entire_manifest | An additional test-only rejecting DB constraint aborts the second partition; no partial rows, receipt/event or consumed ticket remain; retry succeeds after removing that test constraint |
| test_registration_binding_and_secret_hygiene | Exact binding retry succeeds, changed binding conflicts; secret absent from DB/logs; only hash stored; registration creates no attempt |
| test_claim_generation_lease_events_ticket_and_replay | Generation 0→1 once; exact owner/status/deadline formulas; ordered events, scheduler advancement, one receipt; replay never extends lease |
| test_no_work_204_receipt_is_durable_even_after_submission / test_claim_replay_after_unsettled_expiry_never_extends_lease | 204 remains replayable after work arrives; expired historical claim still returns its original description without new generation/lease |
| test_artifact_reservation_requires_live_exact_ownership | Wrong owner/generation/job/schema or expired lease rejected with no reservation |
| test_artifact_reservation_upload_and_no_authority | One reservation, changed expectation conflict, exact bytes/version/hash/schema, one immutable version, explicit zero accepted results and ACTIVE/RUNNING state |
| test_reserved_key_reconciliation_after_real_store_write | Real object written while DB remains RESERVED; gateway retry pins that same version and verifies it without overwrite |
| test_artifact_wrong_actual_output_schema_rejected | Input-format bytes cannot masquerade as output; artifact becomes REJECTED |
| test_m1b_precursor_independent_worker_process | Distinct worker PID; restricted credentials; only assigned slice executed; independent oracle/counters; VERIFIED output with ACTIVE attempt, RUNNING job/partition and zero acceptance |
| test_auth_unknown_fields_and_unimplemented_endpoints | Unauthorized/malformed bodies rejected without leaked values; complete/fail/renew/cancel endpoints absent |
| Unit reference tests | Independent normalization/reducer, deterministic encoding, empty output, strict ISO rejection and checked integer overflow |

Observed suites: **M1B 37 passed** (9 unit + 28 integration), **M1A 122 passed**, **M0 12 passed**. Zero failures, skips, xfails or warnings in successful verification. Final commands, also documented in README:

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
.\.venv\Scripts\uv.exe lock --check --offline --cache-dir .cache/uv
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration -v -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/persistence -v -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/infrastructure tests/storage_contract -v -s --maxfail=1
```

Resolved implementation issues: the harness moved from an inaccessible Windows shared temp directory to workspace-owned temporary children; StreamingBody iteration was corrected to retain the SDK wrapper; the worker's restricted Windows environment now preserves SYSTEMROOT case-insensitively; the deprecated TestClient adapter was replaced. A failed harness representation exposed the local runtime DB password; that representation and secret-check assertions are now redacted, and the runtime password was rotated before subsequent verification. No credential value is recorded here or committed.

## Migration and dependencies

`0002_readiness` adds only the read-only `relay_schema_version` view and SELECT grant. Runtime retains no direct Alembic-table grant and no DDL/admin rights. M1A head assertions now derive the actual Alembic head rather than hardcoding revision 0001; all substantive constraints, role-denial and roundtrip assertions remain. Its fixture output also reports the actual head. All 122 regression cases pass.

Direct additions: FastAPI 0.142.2, uvicorn 0.54.0, PyArrow 25.0.1, HTTPX 0.28.1. Newly added transitive packages: annotated-doc 0.0.5, annotated-types 0.8.0, anyio 4.15.1, certifi 2026.7.22, click 8.5.0, h11 0.16.0, httpcore 1.0.9, idna 3.20, opentelemetry-api 1.45.0, pydantic 2.13.5, pydantic-core 2.46.5, starlette 1.7.0, typing-inspection 0.4.4. opentelemetry-api is an upstream transitive library; no tracing service or tracing instrumentation is configured. Earlier M0/M1A locked package entries are unchanged.

## Remaining obligations and claim boundary

Full T01 requires accepted results and SUCCEEDED states and remains incomplete. M1C must implement fenced publication; M2 must establish concurrent ownership/renewal/idempotency evidence; M3 must add expiry/recovery/retry and the exact generation 4→5 proof. M1B supplies neither automatic lease renewal nor lifecycle settlement. Worker computation errors leave the attempt unsettled, and registered sessions are not automatically stopped on process exit. Retained uploads/orphans have no runtime cleanup or GC.

The gateway currently decodes a whole bounded input shard per assigned slice. Large-shard performance/memory and contention/cap-scale behavior were not measured. Readiness checks revision and store reachability/authentication; the unchanged M0 suite remains the actual store capability gate. No network-partition or adversarial concurrency guarantee is inferred from deterministic key replay or reserved-key reconciliation. Unknown-commit responses preserve uncertainty; full automated operational reconciliation remains later work.

The established M1B claim is a real submit→claim→execute→VERIFIED path with exact-version byte/schema verification and explicit absence of publication authority.
