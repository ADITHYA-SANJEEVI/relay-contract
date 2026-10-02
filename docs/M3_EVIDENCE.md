# M3 recovery, bounded retry and generation fencing evidence

Observed on 2 October 2026 on the existing Windows/Python 3.12.10 checkout, against real Compose PostgreSQL 18.6 and the pinned M0 MinIO. The containing Git commit identifies the shipped implementation. Scope is M3; cancellation/M4 is not started.

## Starting state and previous-pass gate

- Root: `C:\Users\adith\OneDrive\Desktop\relay-contract`; branch `main`; clean starting HEAD `d2cf86ab44c3e1a034279c8873e3ff0517aa9831`.
- Starting remote `main` equalled that HEAD; `gh repo view` returned `isPrivate=true` for the existing `ADITHYA-SANJEEVI/relay-contract` origin.
- All 13 requested contract/evidence documents were read. Claim, renewal, supervisor, publication, receipts, event allocation, schema and migration guards were inspected before edits.
- Pre-edit gates, separately invoked: M2 **25 / 306.82s**; M1C **25 / 174.05s**; M1B **37 / 162.27s**; M1A **122 / 14.74s**; M0 **12 / 3.02s**. No failures/skips/xfails. Accepted evidence and repository agreed.

## Recovery process and authoritative transaction

`scripts/run_recovery.py` is an independent executable loop: default 1-second polls, 100 candidates; `--once` performs one batch. Configuration retains only the runtime DB password/port/database; the end-to-end harness supplies a file containing only these fields and an OS-essential environment. No worker token, operator token, store credential or admin credential is needed. Startup authenticates `current_user=relay_runtime`. There is no in-memory ownership or singleton mutex.

Discovery reads ACTIVE attempts whose lease is at/before an unlocked `clock_timestamp()` initplan bound, ordered by lease/partition against the existing partial expiry index. A read-only relay_runtime EXPLAIN of this exact SQL shape on the retained application DB returned InitPlan 1 and Index Scan using ix_attempts_expiry, with lease_expires_at <= the initplan result; no rows were settled by that inspection. Discovery takes no ownership lock. Each candidate starts a fresh transaction, locks job → partition → attempt, then samples exactly one new DB clock after the final lock. It rechecks linked job/partition, RUNNING states, exact current/latest generation, candidate identity and ACTIVE attempt, and `t >= lease OR t >= hard`. A renewal/publication/earlier recovery winner yields a committed no-op.

Valid settlement changes ACTIVE→EXPIRED, sets finished_at and lease_expired or hard_deadline_exceeded. Budget remaining changes RUNNING→READY with deterministic eligible_at; exhaustion changes RUNNING→FAILED with finished_at. Generation and latest-generation projection are never changed by settlement. Events commit attempt → partition → job under the existing job-local sequence. Recovery errors never schedule from process-local assumptions; a later poll reads durable state again.

## Backoff, caps and drain policy

| Generation | Finished UTC | Original eligible UTC | Backoff seconds |
|---|---|---|---:|
| 1 | 2026-10-02T10:57:46.394960+00:00 | 2026-10-02T10:57:47.394960+00:00 | 1 |
| 2 | 2026-10-02T10:57:48.684423+00:00 | 2026-10-02T10:57:50.684423+00:00 | 2 |
| 3 | 2026-10-02T10:57:50.678261+00:00 | 2026-10-02T10:57:54.678261+00:00 | 4 |
| 4 | 2026-10-02T10:57:52.669779+00:00 | 2026-10-02T10:58:00.669779+00:00 | 8 |
| 5 | 2026-10-02T10:57:54.550562+00:00 | 2026-10-02T10:58:10.550562+00:00 | 16 |
| 6 | 2026-10-02T10:57:56.426143+00:00 | 2026-10-02T10:58:26.426143+00:00 | 30 |
| 7 | 2026-10-02T10:57:58.303703+00:00 | 2026-10-02T10:58:28.303703+00:00 | 30 |
| 8 | 2026-10-02T10:58:00.304700+00:00 | 2026-10-02T10:58:30.304700+00:00 | 30 |
| 9 | 2026-10-02T10:58:02.220289+00:00 | 2026-10-02T10:58:32.220289+00:00 | 30 |

All ten attempts were real HTTP claims followed by real independent recovery processes, not seeded history. Generations 1–9 became EXPIRED/READY; generation 10 became EXPIRED/FAILED and the single-partition job FAILED. Claim returned 204 during the 30-second cap delays (before the explicit test-only eligibility advance), and again after exhaustion. Ten expiry events and nine retry dispositions committed. The fixture asserts the production timestamp formula before advancing only eligible_at under job→partition→attempt locks.

T09 job `4b35a1b9-165d-475a-a599-163238c0d6c9` exhausted exactly three committed claims for target partition `39170cda-2db1-4e14-992b-1d8d1f113856`. Its attempts were generations 1,2,3, all FAILED; duplicate terminal failure did not requeue. The other READY partition still claimed and succeeded; the job remained RUNNING until that healthy publication, which atomically appended JOB_FAILED after the success triple. No ACTIVE attempt or claim above cap remained.

| Target generation | Attempt | Failure finished UTC | Disposition |
|---|---|---|---|
| 1 | 989437b7-0877-4c40-9008-acc4b068b7eb | 2026-10-02T10:57:35.347349+00:00 | READY |
| 2 | ad3a02c8-5256-4a64-8e2d-cd99ed673fa1 | 2026-10-02T10:57:35.614377+00:00 | READY |
| 3 | 81057e5e-4e1c-4fc3-9b97-5ff8db503aad | 2026-10-02T10:57:35.811632+00:00 | FAILED |

The separate DRAIN_RUNNING case failed a nonretryable partition while another actual owner was ACTIVE. The healthy owner renewed, verified and published normally; only then did the job become FAILED.

```json
{
  "accepted": {
    "accepted_at": "2026-10-02T10:58:10.372984+00:00",
    "artifact_id": "e3190652-6cc2-4fd3-b55d-207989e376e3",
    "artifact_uri": "s3://relay-m0-contract/jobs/3ccbaeec-995b-4a50-8934-a6ea959561ec/partitions/1/attempt-1/e3190652-6cc2-4fd3-b55d-207989e376e3/output.parquet?versionId=7d6d872c-62d3-4477-89d2-d2dacbb51d3d",
    "attempt_id": "9160641a-08b5-4a27-b20a-4cddf7514dda",
    "generation": "1",
    "object_version": "7d6d872c-62d3-4477-89d2-d2dacbb51d3d",
    "partition_id": "faf5ed18-b562-4890-a7be-ad5fc71aac72",
    "sha256": "ff2d455a4138c75dcb166e8d8eb6035b423e7417855b86a649b9e6ac617c97f3",
    "size_bytes": "2145"
  },
  "failed_attempt": "7208a34f-339b-47ba-8a13-807a390639b1",
  "job_id": "3ccbaeec-995b-4a50-8934-a6ea959561ec"
}
```

The hard-expiry case waited through the real minimum 60-second attempt lifetime, without editing claimed_at or hard_deadline_at. Claim `d8c83b0d-92f5-4731-a1e1-c200a0ecbb3c` had lease=hard=`2026-10-02T10:59:15.890191+00:00`; DB time crossed at `2026-10-02T10:59:15.893166+00:00`. Real recovery recorded `hard_deadline_exceeded`, generation 1 EXPIRED, partition/job FAILED at max_attempts=1. The VERIFIED output remained immutable and unaccepted.

## Server-classified failure and replay

`POST /v1/attempts/{id}/fail` authenticates the session and uses job→partition→attempt locks and one post-lock clock. Fresh failure requires the canonical LIVE predicate; expired failure rejects lease_expired and lets recovery settle expiry. Wrong owner rejected 403; the final-attempt-lock barrier crossed the real lease before failure evaluated, returning 409 with no state/event mutation.

Exactly supported retryable codes: worker_crash, store_transient, transport_error. Nonretryable: input_invalid, schema_mismatch, workload_validation, integer_overflow. Unknown codes, worker retryable overrides, extra fields, boolean generation, non-object detail and detail above 4,096 canonical UTF-8 bytes rejected 422. Each of the seven codes was tested through the real HTTP API. Raw detail is stored as bounded JSONB, not emitted in events/errors/logs.

The immutable failure fingerprint binds the complete semantic request and attempt ID. An identical FAILED replay reconstructs the same disposition from immutable code/generation/finished_at and immutable job policy, even after a distinct generation-2 owner claims. Changed detail or generation conflicts without affecting current ownership. No new schema or failure response table is needed.

```json
{
  "backoff": {
    "backoff_seconds": 1,
    "eligible_at": "2026-10-02T10:57:30.245640+00:00",
    "finished_at": "2026-10-02T10:57:29.245640+00:00",
    "generation": 1
  },
  "generation": 2,
  "latest_attempt": "0355014c-e541-43e1-8ec3-7ec4c70cc322",
  "original": {
    "attempt_id": "86701415-6222-415f-bbde-5b4bff18cbe6",
    "attempt_status": "FAILED",
    "eligible_at": "2026-10-02T10:57:30.245640+00:00",
    "failure_code": "worker_crash",
    "finished_at": "2026-10-02T10:57:29.245640+00:00",
    "generation": "1",
    "job_id": "dbeafa27-d505-4099-a44a-31591f0230de",
    "partition_id": "b1829fb5-8508-481b-be37-869832ed4829",
    "partition_status": "READY"
  }
}
```

Real rejecting event CHECKs separately aborted failure and expiry after their first mutations. Independent reads proved all attempt/partition/events rolled back; removing only the test CHECK allowed the same operation. API failure abort returned 503/not_committed. Recovery conservatively logged unknown and rescanned, without committing a duplicate disposition.

## T02 actual worker crashes

| Variant | Crashed actual supervisor PID | Actual child PID | Old attempt / owner | Recovery PID | New attempt / owner |
|---|---:|---:|---|---:|---|
| after_claim | 11048 | not started | 69698a28-03b9-4d85-b126-3119648d2641 / 659921e3-c689-43ec-9f57-8b16e03b5088 | 2956 | 266ac9a7-671f-4d92-9514-9ea11bdd1601 / 18e680c6-a07b-4685-b3f5-2dcb71c8a8db |
| mid_execution | 20756 | 12100 | 195d1a0d-1352-43d9-a956-1a1d7f6ec6d7 / 6243a7bd-e516-401d-8f0a-c69a2c937a54 | 22296 | b51b7fe2-ac4f-4391-8caf-00b02904212a / 5c4dadf1-9092-41ae-bb04-fb3b1eb7d861 |

The after-claim barrier holds before child execution/maintenance starts. The mid-execution child uses the production workload aggregation over actual downloaded assigned rows: it consumed three rows, then stayed inside that iteration at the test barrier with a local partial output. The harness terminated the allocated OS process tree (including Windows venv descendants), checked actual supervisor/child liveness false, and observed zero artifact/acceptance from generation 1. It crossed the actual six-second DB lease, ran the real recovery executable, asserted EXPIRED/READY and backoff, advanced only eligibility, and ran a distinct normal CLI worker at generation 2. Both accepted pinned outputs/counters matched the independent serial oracle. No failure endpoint simulated either crash.

```json
{
  "accepted_generation2": {
    "accepted_at": "2026-10-02T10:54:18.029121+00:00",
    "artifact_id": "87143ad5-f51c-4443-afc0-447f52ff4109",
    "artifact_uri": "s3://relay-m0-contract/jobs/31fc54a7-c72a-40d4-b280-2257bd15fd9e/partitions/0/attempt-2/87143ad5-f51c-4443-afc0-447f52ff4109/output.parquet?versionId=58b10025-659c-4cef-9cd8-3101fb670173",
    "attempt_id": "266ac9a7-671f-4d92-9514-9ea11bdd1601",
    "generation": "2",
    "object_version": "58b10025-659c-4cef-9cd8-3101fb670173",
    "partition_id": "fb8c8307-6905-40b1-bcb1-c1f5ed15c376",
    "sha256": "3168790fabecf3e52025c091ffe9775b8e77afeafd384ebe31db9a3cee2d3a78",
    "size_bytes": "2092"
  },
  "backoff": {
    "backoff_seconds": 1,
    "eligible_at": "2026-10-02T10:54:16.211963+00:00",
    "finished_at": "2026-10-02T10:54:15.211963+00:00",
    "generation": 1
  },
  "expired_at": "2026-10-02T10:54:13.583752+00:00",
  "old_attempt": {
    "claimed_at": "2026-10-02T10:54:07.580079+00:00",
    "failure_code": "lease_expired",
    "failure_detail": null,
    "failure_fingerprint": null,
    "finished_at": "2026-10-02T10:54:15.211963+00:00",
    "generation": 1,
    "hard_deadline_at": "2026-10-02T10:55:07.580079+00:00",
    "id": "69698a28-03b9-4d85-b126-3119648d2641",
    "last_renew_fingerprint": null,
    "last_renew_response": null,
    "last_renew_seq": 0,
    "lease_expires_at": "2026-10-02T10:54:13.580079+00:00",
    "partition_id": "fb8c8307-6905-40b1-bcb1-c1f5ed15c376",
    "status": "EXPIRED",
    "worker_session_id": "659921e3-c689-43ec-9f57-8b16e03b5088"
  },
  "phase": "after_claim"
}
```

```json
{
  "accepted_generation2": {
    "accepted_at": "2026-10-02T10:54:36.622880+00:00",
    "artifact_id": "acf0489c-7212-4e86-b5eb-e1b65af8708c",
    "artifact_uri": "s3://relay-m0-contract/jobs/106e5d34-1435-4c01-a8ca-8ec31378d878/partitions/0/attempt-2/acf0489c-7212-4e86-b5eb-e1b65af8708c/output.parquet?versionId=3cdcdfb8-e0c6-4248-84b5-f1180a75eee6",
    "attempt_id": "b51b7fe2-ac4f-4391-8caf-00b02904212a",
    "generation": "2",
    "object_version": "3cdcdfb8-e0c6-4248-84b5-f1180a75eee6",
    "partition_id": "f2bcd3df-776e-4b71-bcbb-0b96372959b6",
    "sha256": "3168790fabecf3e52025c091ffe9775b8e77afeafd384ebe31db9a3cee2d3a78",
    "size_bytes": "2092"
  },
  "backoff": {
    "backoff_seconds": 1,
    "eligible_at": "2026-10-02T10:54:34.761620+00:00",
    "finished_at": "2026-10-02T10:54:33.761620+00:00",
    "generation": 1
  },
  "expired_at": "2026-10-02T10:54:32.143945+00:00",
  "old_attempt": {
    "claimed_at": "2026-10-02T10:54:26.140543+00:00",
    "failure_code": "lease_expired",
    "failure_detail": null,
    "failure_fingerprint": null,
    "finished_at": "2026-10-02T10:54:33.761620+00:00",
    "generation": 1,
    "hard_deadline_at": "2026-10-02T10:55:26.140543+00:00",
    "id": "195d1a0d-1352-43d9-a956-1a1d7f6ec6d7",
    "last_renew_fingerprint": null,
    "last_renew_response": null,
    "last_renew_seq": 0,
    "lease_expires_at": "2026-10-02T10:54:32.140543+00:00",
    "partition_id": "f2bcd3df-776e-4b71-bcbb-0b96372959b6",
    "status": "EXPIRED",
    "worker_session_id": "6243a7bd-e516-401d-8f0a-c69a2c937a54"
  },
  "phase": "mid_execution"
}
```

## T03 expire, recover, reassign

Attempt `11710ed4-633e-4e31-9d29-667e21be5a5e` generation 1 became EXPIRED via real recovery. READY retained generation 1 with exact backoff; only a new HTTP claim created generation 2 attempt `c5e6ab4a-7067-46a2-a598-533ba1145483` owned by `b2129d3f-4eb7-4708-abc1-6650d6da5bc7`. Old heartbeat succeeded as telemetry only; old renew/fail/reserve/complete all rejected. Completion preferred stale_generation; generation-2 ACTIVE ownership and partition projection remained unchanged. The old VERIFIED artifact stayed unaccepted.

```json
{
  "backoff": {
    "backoff_seconds": 1,
    "eligible_at": "2026-10-02T10:54:46.199826+00:00",
    "finished_at": "2026-10-02T10:54:45.199826+00:00",
    "generation": 1
  },
  "new_claim": {
    "attempt_id": "c5e6ab4a-7067-46a2-a598-533ba1145483",
    "claimed_at": "2026-10-02T10:54:45.693678+00:00",
    "generation": "2",
    "hard_deadline_at": "2026-10-02T10:55:45.693678+00:00",
    "inputs": [
      {
        "download_url": "/v1/attempts/c5e6ab4a-7067-46a2-a598-533ba1145483/inputs/0/content",
        "first_row": "0",
        "input_artifact_id": "12f87a37-03df-4751-bea4-a784583d3ca1",
        "object_version": "d3197bf1-96cb-47bc-8f8a-7946f74beef4",
        "row_count": "12",
        "schema_hash": "ef2d6cb7f2010dddeab02b7d5a471909d86bfa7254d270ed78ffb16efb06eb7e",
        "sha256": "95d73e14407a63717535518653f1cb6b52c7c994913a0461807b96246669d8c5"
      }
    ],
    "job_id": "b5cbc4d5-fa6c-4314-b251-d003aa6c3ff2",
    "lease_expires_at": "2026-10-02T10:55:15.693678+00:00",
    "ordinal": 0,
    "parameters": {
      "normalization_version": "1"
    },
    "partition_id": "bbae0da1-f74b-43d5-8db7-b7552460d741",
    "renew_after_seconds": 10,
    "replay": false,
    "worker_session_id": "b2129d3f-4eb7-4708-abc1-6650d6da5bc7",
    "workload": {
      "digest": "sha256:eb65a87ccaee119e6a20914f8efa50bc09bd65703c7b5cc1761b23c7bdb022bc",
      "name": "normalize_aggregate",
      "version": "1"
    }
  },
  "old_attempt": {
    "claimed_at": "2026-10-02T10:54:42.839371+00:00",
    "failure_code": "lease_expired",
    "failure_detail": null,
    "failure_fingerprint": null,
    "finished_at": "2026-10-02T10:54:45.199826+00:00",
    "generation": 1,
    "hard_deadline_at": "2026-10-02T10:55:42.839371+00:00",
    "id": "11710ed4-633e-4e31-9d29-667e21be5a5e",
    "last_renew_fingerprint": null,
    "last_renew_response": null,
    "last_renew_seq": 0,
    "lease_expires_at": "2026-10-02T10:54:42.839372+00:00",
    "partition_id": "bbae0da1-f74b-43d5-8db7-b7552460d741",
    "status": "EXPIRED",
    "worker_session_id": "13282732-63dd-4d46-a7d3-1d9a6d205e87"
  }
}
```

## T04 exact generation 4→5 proof — primary authority evidence

Job `bd750767-4348-452c-bf55-e441d6c2480e`, partition `7668f507-9cbe-4b99-9577-73b0c0d1703f`, ordinal **17**, max_attempts=5. The real immutable manifest contains ordinals 0–17; the preceding 17 partitions were completed normally through HTTP. All zero/one acceptance statements below are scoped to the target partition. Total final job results are 18. The target starts at generation 0; no attempt/generation is inserted or seeded by a fixture.

| Generation | Owner | Terminal state | Artifact | Accepted? |
|---|---|---|---|---|
| 1 | 6aef72f4-60d2-4b1d-9215-59367bf483ef | EXPIRED | none | NO |
| 2 | 6aef72f4-60d2-4b1d-9215-59367bf483ef | EXPIRED | none | NO |
| 3 | 6aef72f4-60d2-4b1d-9215-59367bf483ef | EXPIRED | none | NO |
| 4 | c6ed8770-2444-4305-b103-54f5124de1b6 | EXPIRED | d7e3a285-17c3-42f3-ae6d-276e5a86b2dd | NO |
| 5 | 14bf7fe5-869e-4e21-bf64-88f5a72360a4 | SUCCEEDED | 9f2c8e42-7cc8-475f-8f76-33f3885b6979 | YES |

Generations 1–3 were real HTTP committed claims and real executable recovery settlements. The mutable lease fixture shortened their leases under canonical locks; each original production backoff was asserted before advancing only eligibility.

| Generation | Attempt | Claimed UTC | Settled UTC | Retry delay |
|---|---|---|---|---:|
| 1 | 998cfe14-677b-4c26-9a6c-beef403cdefe | 2026-10-02T10:54:56.871847+00:00 | 2026-10-02T10:54:58.639156+00:00 | 1s |
| 2 | a08655ac-aadc-49bc-9902-2474efa79957 | 2026-10-02T10:54:59.126637+00:00 | 2026-10-02T10:55:01.191346+00:00 | 2s |
| 3 | ecf9a002-266d-413f-a720-55447a374942 | 2026-10-02T10:55:01.515809+00:00 | 2026-10-02T10:55:03.057055+00:00 | 4s |
| 4 | cbd5e956-6fc2-4f9b-ad9a-7c84b2567751 | 2026-10-02T10:55:04.798398+00:00 | 2026-10-02T10:55:12.476672+00:00 | 8s |

Actual worker A PID **20580** claimed generation 4, executed its assigned 12 rows in the real credential-free workload child, and uploaded/readback-verified artifact A. Its test barrier was reached after maintenance.stop(), before any publication request/row lock. Renewal sequence stayed unchanged throughout the pause. The harness crossed the **actual** lease at `2026-10-02T10:55:10.801556+00:00`, then independent recovery PID **26364** committed EXPIRED/READY with generation still 4 and an **8-second** backoff. Artifact A stayed field-for-field VERIFIED, unaccepted, retained.

```json
{
  "artifact_a": {
    "attempt_id": "cbd5e956-6fc2-4f9b-ad9a-7c84b2567751",
    "generation": 4,
    "id": "d7e3a285-17c3-42f3-ae6d-276e5a86b2dd",
    "object_key": "jobs/bd750767-4348-452c-bf55-e441d6c2480e/partitions/17/attempt-4/d7e3a285-17c3-42f3-ae6d-276e5a86b2dd/output.parquet",
    "object_version": "73b6b07b-3aa7-485e-b04d-a0d6293b3260",
    "status": "VERIFIED",
    "verified_at": "2026-10-02T10:55:06.168033+00:00",
    "verified_sha256": "820b66d565fa62d14bffdded1f87a79488d069b0604f9e852c3d80f63b6f823f",
    "verified_size_bytes": 2028
  },
  "generation4_backoff": {
    "backoff_seconds": 8,
    "eligible_at": "2026-10-02T10:55:20.476672+00:00",
    "finished_at": "2026-10-02T10:55:12.476672+00:00",
    "generation": 4
  },
  "renewals_stopped": true
}
```

Worker B PID **16568**, child PID **9900**, boot/session `14bf7fe5-869e-4e21-bf64-88f5a72360a4`, then made the real fifth claim, executed normally and published artifact B. Generation 5 attempt/partition and the whole drained job became SUCCEEDED. New attempt/artifact IDs, attempt-5 key and pinned version differ from A. Deterministic A/B bytes may have the same hash; identity and authority are still distinct.

```json
{
  "exact_accepted_content_check": {
    "bytes": 2028,
    "oracle_groups": 7,
    "sha256": "820b66d565fa62d14bffdded1f87a79488d069b0604f9e852c3d80f63b6f823f"
  },
  "sole_accepted_result": {
    "accepted_at": "2026-10-02T10:55:15.845264+00:00",
    "artifact_id": "9f2c8e42-7cc8-475f-8f76-33f3885b6979",
    "artifact_uri": "s3://relay-m0-contract/jobs/bd750767-4348-452c-bf55-e441d6c2480e/partitions/17/attempt-5/9f2c8e42-7cc8-475f-8f76-33f3885b6979/output.parquet?versionId=8eafd6bb-d553-4b99-af60-6f9a814583c4",
    "attempt_id": "137858b2-0860-48b5-ba5c-3a6864c3de48",
    "generation": "5",
    "object_version": "8eafd6bb-d553-4b99-af60-6f9a814583c4",
    "partition_id": "7668f507-9cbe-4b99-9577-73b0c0d1703f",
    "sha256": "820b66d565fa62d14bffdded1f87a79488d069b0604f9e852c3d80f63b6f823f",
    "size_bytes": "2028"
  }
}
```

A woke and sent its original generation-4 completion/request_id `1782c248-044e-4b47-9d01-ef8db4d496a3`. Both original and exact repeat returned **409/stale_generation**, with the same complete error body. One PUBLICATION_REJECTED event committed for that request ID. A's EXPIRED attempt/artifact A, generation-5 attempt/partition/artifact B and accepted row stayed unchanged. The target has five claims, four expiries, four READY retry transitions, **one** RESULT_ACCEPTED and **one** rejection audit; per-job sequences were contiguous. Operator exact-version bytes/hash and decoded rows/counters matched the independent oracle for rows [204,216).

```json
{
  "first_rejection": {
    "error": {
      "code": "stale_generation",
      "details": {},
      "message": "stale_generation",
      "outcome": "rejected",
      "request_id": "1782c248-044e-4b47-9d01-ef8db4d496a3",
      "retryable": false
    }
  },
  "publication_request": {
    "artifact_id": "d7e3a285-17c3-42f3-ae6d-276e5a86b2dd",
    "artifact_uri": "s3://relay-m0-contract/jobs/bd750767-4348-452c-bf55-e441d6c2480e/partitions/17/attempt-4/d7e3a285-17c3-42f3-ae6d-276e5a86b2dd/output.parquet?versionId=73b6b07b-3aa7-485e-b04d-a0d6293b3260",
    "generation": "4",
    "job_id": "bd750767-4348-452c-bf55-e441d6c2480e",
    "partition_id": "7668f507-9cbe-4b99-9577-73b0c0d1703f",
    "request_id": "1782c248-044e-4b47-9d01-ef8db4d496a3",
    "sha256": "820b66d565fa62d14bffdded1f87a79488d069b0604f9e852c3d80f63b6f823f"
  },
  "repeat_rejection": {
    "error": {
      "code": "stale_generation",
      "details": {},
      "message": "stale_generation",
      "outcome": "rejected",
      "request_id": "1782c248-044e-4b47-9d01-ef8db4d496a3",
      "retryable": false
    }
  },
  "target_event_types": [
    "ATTEMPT_CLAIMED",
    "PARTITION_RUNNING",
    "ATTEMPT_EXPIRED",
    "PARTITION_READY",
    "ATTEMPT_CLAIMED",
    "PARTITION_RUNNING",
    "ATTEMPT_EXPIRED",
    "PARTITION_READY",
    "ATTEMPT_CLAIMED",
    "PARTITION_RUNNING",
    "ATTEMPT_EXPIRED",
    "PARTITION_READY",
    "ATTEMPT_CLAIMED",
    "PARTITION_RUNNING",
    "ARTIFACT_RESERVED",
    "ATTEMPT_EXPIRED",
    "PARTITION_READY",
    "ATTEMPT_CLAIMED",
    "PARTITION_RUNNING",
    "ARTIFACT_RESERVED",
    "ATTEMPT_SUCCEEDED",
    "PARTITION_SUCCEEDED",
    "RESULT_ACCEPTED",
    "PUBLICATION_REJECTED"
  ]
}
```

## T10 real fenced publication abort

Both cases installed an accepted-insertion trigger that first asserted the real fenced partition mutation had executed, then raised SQLSTATE 23514. The API returned 503/not_committed; no acceptance, success event or partial success state survived. VERIFIED artifact metadata stayed unchanged. Removing the test trigger permitted an exact live retry to accept. In the expired variant, that same request instead returned lease_expired, real recovery retained the orphan and generation 2 used a new attempt/artifact/key and accepted normally. The retained M1C abort test also checks that no rejection receipt is fabricated for the aborted transaction.

```json
{
  "after_abort": "live",
  "artifact_id": "bddc8483-6e5c-44f1-9952-9ba4be5963c5",
  "artifact_version": "a6d20696-84c2-4a4f-8433-65db0e97fdd2",
  "outcome": {
    "original_generation": 1,
    "retry": {
      "accepted_result": {
        "accepted_at": "2026-10-02T10:55:49.480373+00:00",
        "artifact_id": "bddc8483-6e5c-44f1-9952-9ba4be5963c5",
        "artifact_uri": "s3://relay-m0-contract/jobs/cc8b999c-6a8f-45ac-a1b2-5c2e25b8e23e/partitions/0/attempt-1/bddc8483-6e5c-44f1-9952-9ba4be5963c5/output.parquet?versionId=a6d20696-84c2-4a4f-8433-65db0e97fdd2",
        "attempt_id": "dd77ab5e-55be-45dc-b1e6-67082cee15b3",
        "generation": "1",
        "object_version": "a6d20696-84c2-4a4f-8433-65db0e97fdd2",
        "partition_id": "1997d573-66b1-4536-b3a4-a9c5629c57b1",
        "sha256": "3168790fabecf3e52025c091ffe9775b8e77afeafd384ebe31db9a3cee2d3a78",
        "size_bytes": "2092"
      },
      "job_status": "SUCCEEDED",
      "replay": false
    }
  }
}
```

```json
{
  "after_abort": "expired",
  "artifact_id": "32d350ea-0e45-48dc-8b56-2237ed96846b",
  "artifact_version": "a8e2b0a8-42a6-43fe-8f89-c32875017963",
  "outcome": {
    "backoff": {
      "backoff_seconds": 1,
      "eligible_at": "2026-10-02T10:55:58.138940+00:00",
      "finished_at": "2026-10-02T10:55:57.138940+00:00",
      "generation": 1
    },
    "new_worker": {
      "accepted_result": {
        "accepted_at": "2026-10-02T10:56:00.385659+00:00",
        "artifact_id": "ae2a3fb8-51c3-4dde-b8c2-474822770add",
        "artifact_uri": "s3://relay-m0-contract/jobs/8a6409e2-4641-40b1-99fb-515b32dbe7a7/partitions/0/attempt-2/ae2a3fb8-51c3-4dde-b8c2-474822770add/output.parquet?versionId=aafee6dd-eab1-4acf-9550-d6b875f4d244",
        "attempt_id": "072c22c9-03c6-4845-a90a-df4d4281e57f",
        "generation": "2",
        "object_version": "aafee6dd-eab1-4acf-9550-d6b875f4d244",
        "partition_id": "f305d590-4965-4831-88fe-abe71ae2592e",
        "sha256": "3168790fabecf3e52025c091ffe9775b8e77afeafd384ebe31db9a3cee2d3a78",
        "size_bytes": "2092"
      },
      "artifact_id": "ae2a3fb8-51c3-4dde-b8c2-474822770add",
      "attempt_id": "072c22c9-03c6-4845-a90a-df4d4281e57f",
      "child_credential_environment_present": false,
      "child_pid": 26544,
      "counters": {
        "input_rows": 12,
        "invalid_reasons": {
          "invalid_record_id": 1,
          "invalid_region": 1
        },
        "invalid_rows": 2,
        "valid_rows": 10
      },
      "elapsed_seconds": 2.328,
      "generation": "2",
      "job_id": "8a6409e2-4641-40b1-99fb-515b32dbe7a7",
      "job_status": "SUCCEEDED",
      "object_version": "aafee6dd-eab1-4acf-9550-d6b875f4d244",
      "original_lease_expires_at": "2026-10-02T10:56:29.265977+00:00",
      "partition_id": "f305d590-4965-4831-88fe-abe71ae2592e",
      "phase": "ACCEPTED",
      "reconciliations": [],
      "renewals": [],
      "sha256": "3168790fabecf3e52025c091ffe9775b8e77afeafd384ebe31db9a3cee2d3a78",
      "size_bytes": "2092",
      "worker_pid": 16676,
      "worker_session_id": "65a454e9-e880-4d98-8469-970d64d8d85e"
    },
    "recovery": [
      {
        "batch": 100,
        "operation": "recovery_start",
        "pid": 26472,
        "poll_seconds": 1
      },
      {
        "attempt_id": "675b064e-d05f-4ee5-a5b1-1ac70cafeeec",
        "attempt_status": "EXPIRED",
        "db_time": "2026-10-02T10:55:57.138940+00:00",
        "eligible_at": "2026-10-02T10:55:58.138940+00:00",
        "failure_code": "lease_expired",
        "finished_at": "2026-10-02T10:55:57.138940+00:00",
        "generation": "1",
        "job_id": "8a6409e2-4641-40b1-99fb-515b32dbe7a7",
        "operation": "recovery",
        "outcome": "expired",
        "partition_id": "f305d590-4965-4831-88fe-abe71ae2592e",
        "partition_status": "READY",
        "reason": "lease_expired"
      },
      {
        "candidates": 1,
        "operation": "recovery_poll"
      }
    ],
    "rejection_code": "lease_expired"
  }
}
```

## T11 and minimum worker uncertainty reconciliation

The production worker retains one boot binding, claim key, reservation, uploaded bytes and completion request ID across up to three transport/503 sends. Claim reconciliation returns the original durable receipt and performs current GET ownership validation before a child. Complete uncertainty inspects GET attempt and retries the identical completion; it never creates another output identity because a response is absent. Lease expiry can invalidate a fresh attempt but cannot erase historical acceptance. Exhausted uncertainty exits explicitly; this is not a general workflow engine.

Each T11 actual worker lost a real committed claim response, then received 200 on the same claim key. After a real publication 201 COMMIT, the localhost transport boundary discarded success, crossed the actual nominal lease without editing terminal metadata, and either raised a transport read error or returned an injected 503/unknown. GET showed SUCCEEDED/the matching accepted identity. The same request_id/body retry returned historical 200/replay with exactly the same accepted_at/artifact/hash/version/generation. One claim receipt, attempt, accepted row and success event set existed. The 503 is explicitly a transport-boundary uncertainty injection; no actual PostgreSQL connection was killed during COMMIT. Existing API disconnect-vs-known-abort classification remains unchanged.

```json
{
  "GET_reconciliation": [
    {
      "accepted_result": {
        "accepted_at": "2026-10-02T10:55:25.145954+00:00",
        "artifact_id": "76e7abcb-d41d-49da-934d-2f15da7719a6",
        "artifact_uri": "s3://relay-m0-contract/jobs/31c3c293-1b6d-453d-a42e-a01f9a13eacd/partitions/0/attempt-1/76e7abcb-d41d-49da-934d-2f15da7719a6/output.parquet?versionId=15df565f-9da5-436f-96b2-63d793f2a1c1",
        "attempt_id": "2c715cd3-535c-4601-94d2-e60cf725cbda",
        "generation": "1",
        "object_version": "15df565f-9da5-436f-96b2-63d793f2a1c1",
        "partition_id": "0e944846-562d-4d91-ad87-687955aae7bd",
        "sha256": "3168790fabecf3e52025c091ffe9775b8e77afeafd384ebe31db9a3cee2d3a78",
        "size_bytes": "2092"
      },
      "operation": "complete",
      "status": "SUCCEEDED"
    }
  ],
  "accepted_result": {
    "accepted_at": "2026-10-02T10:55:25.145954+00:00",
    "artifact_id": "76e7abcb-d41d-49da-934d-2f15da7719a6",
    "artifact_uri": "s3://relay-m0-contract/jobs/31c3c293-1b6d-453d-a42e-a01f9a13eacd/partitions/0/attempt-1/76e7abcb-d41d-49da-934d-2f15da7719a6/output.parquet?versionId=15df565f-9da5-436f-96b2-63d793f2a1c1",
    "attempt_id": "2c715cd3-535c-4601-94d2-e60cf725cbda",
    "generation": "1",
    "object_version": "15df565f-9da5-436f-96b2-63d793f2a1c1",
    "partition_id": "0e944846-562d-4d91-ad87-687955aae7bd",
    "sha256": "3168790fabecf3e52025c091ffe9775b8e77afeafd384ebe31db9a3cee2d3a78",
    "size_bytes": "2092"
  },
  "claim_key": "009b6cb2-8d2d-4174-9a8c-06d6a076027c",
  "completion_request_id": "afc3d50f-9aa4-4ae4-a1ed-4e2e169147c3",
  "crossed_db_time": "2026-10-02T10:55:29.631875+00:00",
  "first_status": 201,
  "retry_status": 200,
  "uncertainty": "transport_loss",
  "worker_pid": 24964
}
```

```json
{
  "GET_reconciliation": [
    {
      "accepted_result": {
        "accepted_at": "2026-10-02T10:55:38.698197+00:00",
        "artifact_id": "1c93a189-4958-4be4-83fb-fee36420147e",
        "artifact_uri": "s3://relay-m0-contract/jobs/cb6b3449-85f2-46e0-8cb9-4161626e45ae/partitions/0/attempt-1/1c93a189-4958-4be4-83fb-fee36420147e/output.parquet?versionId=f9928f87-5e54-4a2a-b37c-c619109e71c4",
        "attempt_id": "0d46450e-d25e-41dd-a9db-05c779836dd6",
        "generation": "1",
        "object_version": "f9928f87-5e54-4a2a-b37c-c619109e71c4",
        "partition_id": "a05771f4-2653-4611-be55-bfcf31c11b3f",
        "sha256": "3168790fabecf3e52025c091ffe9775b8e77afeafd384ebe31db9a3cee2d3a78",
        "size_bytes": "2092"
      },
      "operation": "complete",
      "status": "SUCCEEDED"
    }
  ],
  "accepted_result": {
    "accepted_at": "2026-10-02T10:55:38.698197+00:00",
    "artifact_id": "1c93a189-4958-4be4-83fb-fee36420147e",
    "artifact_uri": "s3://relay-m0-contract/jobs/cb6b3449-85f2-46e0-8cb9-4161626e45ae/partitions/0/attempt-1/1c93a189-4958-4be4-83fb-fee36420147e/output.parquet?versionId=f9928f87-5e54-4a2a-b37c-c619109e71c4",
    "attempt_id": "0d46450e-d25e-41dd-a9db-05c779836dd6",
    "generation": "1",
    "object_version": "f9928f87-5e54-4a2a-b37c-c619109e71c4",
    "partition_id": "a05771f4-2653-4611-be55-bfcf31c11b3f",
    "sha256": "3168790fabecf3e52025c091ffe9775b8e77afeafd384ebe31db9a3cee2d3a78",
    "size_bytes": "2092"
  },
  "claim_key": "d4062a8f-3d0e-4017-82d0-cf9e1fa3cc2d",
  "completion_request_id": "1860c76e-e049-4036-99db-17dc102b7cf8",
  "crossed_db_time": "2026-10-02T10:55:42.994153+00:00",
  "first_status": 201,
  "retry_status": 200,
  "uncertainty": "unknown_503",
  "worker_pid": 21868
}
```

## T23 race winner evidence and T26

Renewal-first uses an attempt-update advisory barrier after the canonical locks/time: renewal evaluated while live, but remained uncommitted past the old deadline. Real unlocked discovery observed the old expired ACTIVE row through MVCC; a recovery connection waited behind its job lock. Releasing the barrier committed renewal; recovery sampled fresh post-lock time, saw the extended lease and did nothing.

```json
{
  "discovered_at": "2026-10-02T10:56:07.536194+00:00",
  "old_deadline": "2026-10-02T10:56:07.532615+00:00",
  "recovery": {
    "attempt_id": "82e61202-6e8a-4511-901b-22c8e5090193",
    "db_time": "2026-10-02T10:56:07.601769+00:00",
    "generation": "1",
    "job_id": "473cd81b-a2a2-4311-9fcf-06f77de54848",
    "operation": "recovery",
    "outcome": "noop",
    "partition_id": "86da682c-f437-437b-806b-d76fed16060b",
    "reason": "still_live"
  },
  "renewal": {
    "applied": true,
    "db_time": "2026-10-02T10:56:06.973309+00:00",
    "hard_deadline_at": "2026-10-02T11:06:05.968962+00:00",
    "lease_expires_at": "2026-10-02T10:56:36.973309+00:00",
    "sequence": "1"
  },
  "waiters": [
    {
      "pid": 185671,
      "wait_event": "advisory"
    },
    {
      "pid": 185680,
      "wait_event": "transactionid"
    }
  ]
}
```

Recovery-first held an EXPIRED-update barrier with the already-invalid attempt. A delayed renewal waited on a separate PostgreSQL backend. After expiry commit renewal rejected lease_expired, sequence stayed 0, and exactly one READY retry disposition/event set committed.

```json
{
  "backoff": {
    "backoff_seconds": 1,
    "eligible_at": "2026-10-02T10:56:14.327584+00:00",
    "finished_at": "2026-10-02T10:56:13.327584+00:00",
    "generation": 1
  },
  "recovery": {
    "attempt_id": "44e8fd7e-c8f6-4031-9580-91b87802f364",
    "attempt_status": "EXPIRED",
    "db_time": "2026-10-02T10:56:13.327584+00:00",
    "eligible_at": "2026-10-02T10:56:14.327584+00:00",
    "failure_code": "lease_expired",
    "finished_at": "2026-10-02T10:56:13.327584+00:00",
    "generation": "1",
    "job_id": "bf940cc3-20d9-47d0-aba1-43faeed63746",
    "operation": "recovery",
    "outcome": "expired",
    "partition_id": "7a5480f8-8b52-4618-afb7-f0df04714d67",
    "partition_status": "READY",
    "reason": "lease_expired"
  },
  "renewal_code": "lease_expired",
  "waiters": [
    {
      "pid": 185711,
      "wait_event": "advisory"
    },
    {
      "pid": 185701,
      "wait_event": "transactionid"
    }
  ]
}
```

Failure/publication orderings used the same canonical locks on independent real HTTP connections. Publication-first returned 201 then failure 409/terminal_job: SUCCEEDED plus one accepted row, zero retry. Failure-first returned 200 then publication 409/attempt_terminal: FAILED/READY, no acceptance, one retry. The already-VERIFIED artifact was unchanged and unaccepted for the failure winner. Never accepted result plus FAILED attempt.

```json
{
  "accepted_count": 1,
  "attempt_id": "6508f1fb-a2dd-4ce6-a02c-92811402b45f",
  "event_types": [
    "JOB_SUBMITTED",
    "ATTEMPT_CLAIMED",
    "PARTITION_RUNNING",
    "JOB_RUNNING",
    "ARTIFACT_RESERVED",
    "ATTEMPT_SUCCEEDED",
    "PARTITION_SUCCEEDED",
    "RESULT_ACCEPTED",
    "JOB_SUCCEEDED"
  ],
  "loser_code": "terminal_job",
  "statuses": [
    201,
    409
  ],
  "terminal_state": "SUCCEEDED",
  "waiting_backends": [
    {
      "pid": 185733,
      "wait_event": "advisory"
    },
    {
      "pid": 185744,
      "wait_event": "transactionid"
    }
  ],
  "winner": "publication"
}
```

```json
{
  "accepted_count": 0,
  "attempt_id": "4fdae3de-3641-4d05-89f5-6edbe3f3b422",
  "event_types": [
    "JOB_SUBMITTED",
    "ATTEMPT_CLAIMED",
    "PARTITION_RUNNING",
    "JOB_RUNNING",
    "ARTIFACT_RESERVED",
    "ATTEMPT_FAILED",
    "PARTITION_READY",
    "PUBLICATION_REJECTED"
  ],
  "loser_code": "attempt_terminal",
  "statuses": [
    200,
    409
  ],
  "terminal_state": "FAILED",
  "waiting_backends": [
    {
      "pid": 185765,
      "wait_event": "advisory"
    },
    {
      "pid": 185784,
      "wait_event": "transactionid"
    }
  ],
  "winner": "failure"
}
```

M3 T26 additionally let recovery discover an expired candidate while publication was held after a valid real fenced mutation. Recovery waited on the job lock; publication committed after nominal expiry legally; recovery then observed SUCCEEDED and performed no mutation. This preserves the frozen linearization contract; all earlier M1C T26 tests also passed.

```json
{
  "crossed": "2026-10-02T10:56:42.890754+00:00",
  "deadline": "2026-10-02T10:56:42.887258+00:00",
  "publication": {
    "accepted_result": {
      "accepted_at": "2026-10-02T10:56:42.359878+00:00",
      "artifact_id": "08fe97f7-7075-4e96-9f6c-4328684f7e91",
      "artifact_uri": "s3://relay-m0-contract/jobs/2a45f7f5-794f-4235-b1a4-6c2e2954417d/partitions/0/attempt-1/08fe97f7-7075-4e96-9f6c-4328684f7e91/output.parquet?versionId=92561fb2-f884-42fe-a417-675d24b6087b",
      "attempt_id": "f2975d11-4aac-464d-9f41-5a061a980370",
      "generation": "1",
      "object_version": "92561fb2-f884-42fe-a417-675d24b6087b",
      "partition_id": "731a8e73-03a8-4bfb-9a6c-617d08fad1cb",
      "sha256": "3168790fabecf3e52025c091ffe9775b8e77afeafd384ebe31db9a3cee2d3a78",
      "size_bytes": "2092"
    },
    "job_status": "SUCCEEDED",
    "replay": false
  },
  "recovery": {
    "attempt_id": "f2975d11-4aac-464d-9f41-5a061a980370",
    "db_time": "2026-10-02T10:56:43.003319+00:00",
    "generation": "1",
    "job_id": "2a45f7f5-794f-4235-b1a4-6c2e2954417d",
    "operation": "recovery",
    "outcome": "noop",
    "partition_id": "731a8e73-03a8-4bfb-9a6c-617d08fad1cb",
    "reason": "already_settled_or_superseded"
  },
  "waiters": [
    {
      "pid": 185844,
      "wait_event": "transactionid"
    },
    {
      "pid": 185835,
      "wait_event": "advisory"
    }
  ]
}
```

## Multiple recovery processes and restart

Two independently booted real recovery loops, already ready before expiry, discovered the same candidate. One backend waited at the expiry advisory barrier and another at the job lock. Results were one expired, one noop/already_settled_or_superseded. The attempt became EXPIRED once, the partition READY once, generation remained 1 and only ATTEMPT_EXPIRED/PARTITION_READY were appended. Both loops were terminated after their outcomes; a new executable process scanned zero candidates. Original eligible_at, partition state and all events were unchanged on restart.

```json
{
  "backoff": {
    "backoff_seconds": 1,
    "eligible_at": "2026-10-02T10:59:27.783312+00:00",
    "finished_at": "2026-10-02T10:59:26.783312+00:00",
    "generation": 1
  },
  "logs": [
    [
      {
        "batch": 100,
        "operation": "recovery_start",
        "pid": 12888,
        "poll_seconds": 1
      },
      {
        "candidates": 0,
        "operation": "recovery_poll"
      },
      {
        "attempt_id": "bef4cf76-2506-43b5-989b-3c47b206b9b2",
        "attempt_status": "EXPIRED",
        "db_time": "2026-10-02T10:59:26.783312+00:00",
        "eligible_at": "2026-10-02T10:59:27.783312+00:00",
        "failure_code": "lease_expired",
        "finished_at": "2026-10-02T10:59:26.783312+00:00",
        "generation": "1",
        "job_id": "88bdab62-ab89-4376-bc49-dfe0de4a6745",
        "operation": "recovery",
        "outcome": "expired",
        "partition_id": "d81fee89-204f-41b1-a449-2a8fffc038a3",
        "partition_status": "READY",
        "reason": "lease_expired"
      }
    ],
    [
      {
        "batch": 100,
        "operation": "recovery_start",
        "pid": 24812,
        "poll_seconds": 1
      },
      {
        "candidates": 0,
        "operation": "recovery_poll"
      },
      {
        "attempt_id": "bef4cf76-2506-43b5-989b-3c47b206b9b2",
        "db_time": "2026-10-02T10:59:26.938529+00:00",
        "generation": "1",
        "job_id": "88bdab62-ab89-4376-bc49-dfe0de4a6745",
        "operation": "recovery",
        "outcome": "noop",
        "partition_id": "d81fee89-204f-41b1-a449-2a8fffc038a3",
        "reason": "already_settled_or_superseded"
      }
    ]
  ],
  "restart": [
    {
      "batch": 100,
      "operation": "recovery_start",
      "pid": 22708,
      "poll_seconds": 1
    },
    {
      "candidates": 0,
      "operation": "recovery_poll"
    }
  ],
  "waiters": [
    {
      "pid": 186542,
      "wait_event": "transactionid"
    },
    {
      "pid": 186541,
      "wait_event": "advisory"
    }
  ]
}
```

## Final regression and repository checks

| Gate | Passed | Duration |
|---|---:|---:|
| M3 | 29 | 342.22s |
| M2 | 25 | 280.78s |
| M1C | 25 | 164.82s |
| M1B | 37 | 159.54s |
| M1A | 122 | 13.97s |
| M0 | 12 | 2.69s |

All six were separate pytest invocations, serial for API-heavy tests. No final failures, skips, xfails or pytest warnings.

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
.\.venv\Scripts\python.exe -m pytest tests/faults -q -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/concurrency -q -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/publication -q -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration -q -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/persistence -q --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/infrastructure tests/storage_contract -q --maxfail=1
.\.venv\Scripts\python.exe -m compileall -q src scripts tests
.\.venv\Scripts\uv.exe lock --check --offline --cache-dir .cache/uv
git diff --check
```

The candidate full M3 run passed 29 in 346.60s before the final gate. Compile/whitespace/offline lock and actual current-local-credential byte scan passed without printing secret values. No dependency/migration/schema/grant/Compose change. FENCED_UPDATE and claim implementation were compared unchanged to accepted M2; publication changes only final drain aggregation. Existing renewal code is unchanged. The old M1B fail=404 assertion became unauthenticated fail=401 because M3 implements that route; cancel remains 404. No earlier safety assertion was removed, skipped or weakened.

Development failures are excluded from acceptance: the initial multi-recovery observer timed out on OS startup before its 1.5-second lock observation deadline. The harness now boots both real loops before inducing expiry, retaining all production timeouts. The first T04 run reached VERIFIED/expired generation 4, then a test passed a native UUID to an older string-only row helper. String conversion fixed that assertion; the complete process suite then passed 8 in 124.07s. The mid-execution harness was strengthened to pause inside production aggregation after three assigned rows, rather than claim a generic CPU loop alone established workload execution. No hidden retries/skips or host/dependency changes were introduced. The M2 PyArrow startup incident remains an observed historical host risk; it did not recur in the recorded M3 baseline/candidate/final gates.

## Scope and remaining obligations

Every stateful API scenario used a fresh UUID-named migrated PostgreSQL database and an independent localhost API process. Runtime transitions authenticated as relay_runtime; trusted migration identity was used only for fixture allocation/inspection/fault triggers. Real MinIO conditional writes/readback and pinned-version reads were used. Fixture cleanup drops only the allocated test DB/cache child after owned processes exit. M3 object versions/orphans are retained; no M3 object deletion/GC/key reuse occurs. The unchanged M1C integrity regression still deliberately deletes only its own pinned fixture version using trusted store admin authority, as documented in M1C evidence. The original retained M1B/M2 application trace was not settled or rewritten. Crash-killed local temporary task files may remain under ignored .cache/workers; they carry no authority.

M3 establishes the tested crash/lease recovery, bounded retry and stale-generation fencing cases, and at most one accepted result per immutable partition. It does not establish exactly-once computation/external side effects, complete V1, production readiness, throughput/scaling or a real-time recovery SLA. Cancellation, poison/hang lifecycle, full API/DB/store outage/restart matrix, metrics/benchmark/release work remain M4+. Actual PostgreSQL COMMIT disconnects, arbitrary host/network partitions and volume loss were not tested here. Recovery must be running and fresh workers must poll after eligibility for progress. Registered sessions are not automatically STOPPED on exit and still count toward capacity; child termination is best-effort, while DB fencing supplies authority safety. The worker reconciliation loop is bounded and does not persist a client workflow across process restart. Whole-shard decoding and per-job/scheduler serialization remain unmeasured resource limits.

No M4 or cancellation implementation is present. Stop at M3. The final task report records the pushed commit and remote equality; this evidence intentionally contains no self-referential ending commit hash.
