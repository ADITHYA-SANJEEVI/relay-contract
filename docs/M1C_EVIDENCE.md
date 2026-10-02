# M1C evidence — fenced publication and accepted results

Observed on 2 October 2026 against real Compose PostgreSQL 18.6 and the existing pinned MinIO build, with Python 3.12.10. Starting branch `main`, clean HEAD `b12f245fdd4fbacc40f468873ead9f2c9919040d`. Remote main matched and the existing origin remained private. The shipped ending commit is the commit introducing this document: resolve it with `git log --diff-filter=A -1 --format=%H -- docs/M1C_EVIDENCE.md`; the final task report records the literal ending HEAD and remote equality. No prior history is rewritten.

## Previous-pass gate

Before implementation, the accepted M1B suite passed **37 tests in 159.47s**, M1A passed **122 in 14.39s**, and M0 passed **12 in 2.86s**. Services were healthy. All frozen contract documents and both earlier persistence/execution evidence documents were read, and current claim, reservation, gateway, events, schema, guards and runtime connection infrastructure were inspected.

M1C changes no migration, schema, trigger, runtime grant, workload rules, dependency version or lease policy. The runtime still authenticates directly as `relay_runtime`; the gateway uses only the existing runtime store identity. Worker processes receive only API bootstrap credentials and OS essentials. Existing M1B execution still supports a VERIFIED/unaccepted stop.

## Implemented boundary

`POST /v1/attempts/{id}/complete` accepts the frozen identity fields, rejects unknown fields and bounds request IDs to 128 characters. The verified artifact response supplies its canonical registered URI: `s3://bucket/key?versionId=<URL-encoded opaque version>`. The caller's URI is compared exactly to registered metadata; arbitrary URLs are never fetched. The publication fingerprint binds job, partition, attempt, generation, artifact, bucket/key/version, size and SHA-256, excluding request ID. Rejection receipt hashes bind the supplied semantic request, independent of later prerequisite correction.

The publication transaction uses job → partition → attempt locks. It checks durable rejection receipts and historical acceptance before current job/lease rejection. Exact acceptance replay resolves immutable accepted metadata without applying fresh ownership checks. Fresh publication then locks the artifact, requires VERIFIED and exact identity, and samples one `clock_timestamp()` after the final authoritative lock.

The actual conditional `UPDATE partitions ... FROM jobs, attempts, artifacts` checks every canonical ownership condition together, all identity links, strict lease and hard-deadline inequalities, exact verified artifact identity, and absence of an accepted result. **Affected row count 1 is the new-authority gate.** Only afterward does the same transaction insert the immutable accepted row, settle the attempt, append ordered events and set the job SUCCEEDED if every partition succeeded. Accepted-result PK/unique/FKs and unchanged deferred guards provide additional cardinality and consistency barriers. No accepted UPSERT/update exists. Success is returned after transaction scope commits; database errors roll back or report uncertainty according to the existing API handler.

No storage I/O, parsing or workload computation occurs in publication. A known rejection commits only its receipt and, for a known job, a PUBLICATION_REJECTED event under the job sequence. Correctly linked attempt IDs alone enter event FKs. Unknown-job rejections have a receipt without a fabricated job event. Repeated rejected request IDs return their stored outcome; changed payload conflicts; correcting prerequisites uses a new ID. Expected duplicate receipt insertion races roll back and read the committed winner in a fresh transaction.

## Fresh acceptance and atomicity

Observed live acceptance:

| Field | Value |
|---|---|
| Job | `84ad21fa-44a1-4f01-b60c-b77d877eb604` |
| Partition | `9618c4ab-fa96-49cc-93cd-ea02e2709023` |
| Attempt | `131e1c60-10bb-4e55-9abf-4f190253c362`, generation 1 |
| Artifact | `5089bfd7-6963-4e2a-878f-49c4adee880b` |
| Exact version | `b721354f-ef0b-473a-acaa-404567e07ac9` |
| SHA-256 | `3168790fabecf3e52025c091ffe9775b8e77afeafd384ebe31db9a3cee2d3a78` |
| Size | 2,092 bytes |
| Claimed UTC | `2026-10-02T07:33:52.838794+00:00` |
| Accepted UTC | `2026-10-02T07:33:53.274152+00:00` |
| Initial lease deadline UTC | `2026-10-02T07:34:22.838794+00:00` |

HTTP 201, replay=false. PostgreSQL held one accepted row, SUCCEEDED attempt/partition/job, matching finished timestamps and unchanged VERIFIED artifact metadata. GET job returned complete=true and accepted count 1. Partition/attempt reads exposed the actual acceptance. The final event order was ATTEMPT_SUCCEEDED → PARTITION_SUCCEEDED → RESULT_ACCEPTED → JOB_SUCCEEDED, with one shared accepted timestamp and completion request ID, and contiguous job-local sequence.

`test_abort_after_fenced_mutation_rolls_back_all_success` installed an additional test-only rejecting trigger on accepted insertion in its disposable database. The trigger first verified the partition was already SUCCEEDED in that transaction, then raised SQLSTATE 23514. HTTP returned 503/not_committed. Independent reads showed partition RUNNING, attempt ACTIVE, no accepted row, and exactly the pre-publication events. No rejection receipt fabricated committed history for this DB abort. Removing only the added trigger allowed the same completion to succeed. All original guards remained enabled.

## Replay, conflicts and rejection audit

An accepted completion returned 200/replay=true for both the original and a new request ID after the real DB-clock lease deadline passed. All accepted fields, including accepted_at, remained identical; there was one RESULT_ACCEPTED event and one success transition set.

Different artifact ID, SHA, URI and newer generation returned 409/result_conflict after acceptance. Older generation preferred 409/stale_generation. A separately recorded attempt for another partition could not replace the accepted partition's result. Accepted rows remained field-for-field unchanged. Repeated conflicting request IDs produced one durable rejection audit each.

Wrong owner returned 403; wrong generation/artifact/hash/external URI returned conflicts; missing job/attempt returned 404. All left ownership and authority unchanged. An initially RESERVED artifact produced artifact_not_verified; identical request replay remained that rejection after upload. Corrected identity with the same ID conflicted, while a new ID could succeed. Unknown fields and oversized request IDs returned 422 before mutation.

## Expiry and T26 linearization

Fresh completion after test-only lease shortening under job → partition → attempt locks returned 409/lease_expired. PostgreSQL retained ACTIVE/RUNNING unsettled states, zero accepted rows and no success events. Replaying the rejected request did not duplicate its audit. No recovery/reassignment was invoked.

The final-artifact-lock test blocked publication at the last row lock, crossed the shortened deadline, then released the lock. Publication rejected as lease_expired, proving validity is sampled after waiting for that lock. Separate actual SQL tests bound t exactly equal to lease expiry and hard deadline: both affected zero rows.

T26 used a test-only accepted-insertion trigger that checked the actual fenced partition mutation had already succeeded, then waited on an advisory-lock barrier. No production hook/endpoint exists. Observed:

- Accepted decision time: `2026-10-02T07:35:44.207198+00:00`
- Lease deadline: `2026-10-02T07:35:44.668826+00:00`
- Barrier released: `2026-10-02T07:35:44.677722+00:00`
- Runtime backend 137007 was observed waiting on the advisory barrier.

The response was 201 and the job SUCCEEDED. The sampled acceptance preceded expiry; physical commit necessarily followed barrier release after expiry. Production 2s lock/5s statement/idle timeouts were retained. This establishes the documented linearization semantics, not a response-time lease check or a tested recovery service.

## Basic T05 concurrency

Two independent HTTP clients reached distinct PostgreSQL runtime connections concurrently. Backend 136976 waited at the post-fence advisory barrier; backend 136986 waited on the first transaction's job lock (`transactionid`). After release, statuses were **201 and 200**, with identical accepted identity, one accepted row and one success event set. A subsequent changed-SHA completion returned 409 and left the result unchanged.

The test coordinates requests using a database barrier, never a Python serialization mutex. Its initial observer failed because transaction-scoped PostgreSQL activity snapshots did not refresh; the observer now uses AUTOCOMMIT and subsequent real contention checks passed. PostgreSQL documents the snapshot behavior in its [statistics documentation](https://www.postgresql.org/docs/18/monitoring-stats.html). The fix changes only the test observer, not production lock or timeout semantics.

## Full T01: independent workers and oracle

Observed job `d135c932-19b6-4793-ae8a-402a4b020a2c`, input `791621be-1a64-47ec-9100-ff33e6ff2feb`: 36 deterministic records, slices [0,9), [9,22), [22,36). Three independent worker boots ran the actual HTTP path with `--complete`. Each registered, claimed generation 1, downloaded only assigned slices, executed, reserved, uploaded/readback-verified and completed.

| Ordinal | Worker PID / duration | Attempt | Accepted artifact / pinned version |
|---|---|---|---|
| 0 | 21832 / 1.390s | `0c19c3fa-c6cb-4ca2-bd31-396f77df28cf` | `10d8c4f8-1051-4866-8570-e5b7d8523e89` / `033e8b65-7e21-415e-b355-10efacc7d84b` |
| 1 | 19560 / 1.344s | `ed8ecc12-0eef-42af-acbf-acb4b136e8c5` | `ff48cdd1-42c9-4069-9f71-0d006b23e7b4` / `b500bfb9-13fd-40bc-b1a0-11fe1f1d1c39` |
| 2 | 8100 / 1.391s | `e13864db-7f77-4785-9e5f-7378b0a3bc55` | `293248d3-e258-4c64-8184-8127a2e1aeb1` / `6fc891e1-c751-4e58-9f58-fb5bf048649e` |

Output SHA-256 by ordinal:

0. `fcbd60978f461431fe2aef7dc65bc5f9188290017cf6affa05e951a466bf7a63` (1,969 bytes)
1. `28cd7bf29a676b4759edba88182aade65984a27209101932d86b206e0a7ea1de` (2,143 bytes)
2. `4a405288a85d7a6a560ea8bc82d4b0b7919f3de382f86472dd8c02c09917d081` (2,144 bytes)

Every decoded partition output and its counters matched the independent serial oracle for its exact slice. A separate client-side integer reducer over accepted partition aggregates matched the complete 36-record oracle: **14 groups**, 30 valid and 6 invalid records. This is client-side validation, not a distributed reduce stage. Each worker finished comfortably within its unchanged 30s initial lease. All sessions and PIDs were distinct and different from API/test processes; process output/log checks found no credentials.

PostgreSQL inspection found all three partitions and latest attempts SUCCEEDED, exactly one accepted row each, and job SUCCEEDED. GET job/results returned complete=true and partial_result_count=partition_count=3. Acceptance identity matched each exact verified artifact. The job had 21 contiguous events, three ordered success triples, and one final JOB_SUCCEEDED.

These traces were observed in UUID-named real-service test databases. Independent runtime reads inspected committed state before fixture cleanup; those disposable databases were then dropped. Immutable test objects remain in MinIO, except the explicitly deleted version in the separate integrity-failure test. The earlier retained M1B application trace was not altered or newly accepted.

## Result read integrity

GET results uses a read-only REPEATABLE READ snapshot for job status/count and the ordinal page. Only accepted rows appear; unaccepted VERIFIED outputs are absent. Exact pinned-version download, SHA/size and Parquet schema validation happen after the connection closes. Operator content reads require acceptance; owning-worker content reads require its own VERIFIED artifact. Successful reads include SHA/version headers.

The integrity test wrote a newer version at its own disposable fixture key using the trusted admin. Reads still returned the original pinned accepted version and its SHA. It then removed only that fixture's original version: both result manifest and content reads returned 422/integrity_failure and structured error logs. Accepted/artifact metadata stayed unchanged; no newer-version substitution or recomputation occurred. No integrity-incidents persistence subsystem was added.

## Verification commands and scope

M1C implementation verification: **25 passed in 162.22s**. Final regression after staged diff review, credential/generated-file scan, syntax checks and unchanged-dependency/schema/guard checks:

| Suite | Final observed result |
|---|---|
| M1C publication | **25 passed**, 179.48s |
| M1B unit/integration | **37 passed**, 173.06s |
| M1A persistence | **122 passed**, 21.72s |
| M0 infrastructure/storage | **12 passed**, 4.40s |

No final failures, skips, xfails or warnings. The dependency lock check passed, with no package additions/changes. Final T01 independently repeated the full trace for job `0d0b3600-b9ca-4fd1-be36-1ceca98d9959` in disposable database `relay_m1b_test_444c09480bde451b8e876682c2463f84`: API PID 17272; worker PIDs 24584, 18096 and 14808, durations 1.719s, 1.735s and 1.562s. All three accepted outputs matched their slice oracles, the combined oracle again had 14 groups, and the same 21-event order and SUCCEEDED/count=3 state held. The separately rerun M1B worker retained VERIFIED_UNACCEPTED with zero acceptance. Only evidence text was updated after this regression; tested source stayed unchanged.

Commands for separately runnable milestone suites:

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
.\.venv\Scripts\uv.exe lock --check --offline --cache-dir .cache/uv
.\.venv\Scripts\python.exe -m pytest tests/publication -q -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration -q -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/persistence -q -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/infrastructure tests/storage_contract -q -s --maxfail=1
```

The M1B forbidden-endpoint test now expects authentication rejection for the newly authorized complete route and still requires renew/fail/cancel to be absent. Its verify-only real-process precursor and zero-authority assertions remain. No earlier test was removed/skipped/xfail'd. No dependencies changed.

## Remaining obligations

M1C proves fresh fenced publication, immutable historic acceptance/replay, durable rejection audit, basic T05 contention, T26 and full normal T01. It does not prove exactly-once execution, recovery, cancellation, lease renewal, 32-worker claim contention, adversarial network partitions, automatic unknown-commit reconciliation or generation reassignment. The exact 4→5 stale-worker proof remains M3.

Expired attempts stay ACTIVE/unsettled without a reaper. Sessions are not automatically STOPPED on process exit; the configured 32-session bound can eventually require later lifecycle management. Uploads/orphans remain retained with no GC. Bounded whole-shard decoding and per-page result verification can consume memory/I/O; large-shard/cap-scale performance was not measured. Work exceeding the initial lease cannot newly publish, and no supervisor extends it. Structured integrity logs exist; no new metrics stack or durable incident subsystem is claimed. M2 was not started.
