# M2 concurrent ownership and lease evidence

Observed on 2 October 2026 on the existing Windows checkout. Scope: M2 only. The containing Git commit identifies the shipped implementation; no self-referential commit hash is embedded here. M3 recovery/reassignment has not started.

## Starting state and baselines

- Root: `C:\Users\adith\OneDrive\Desktop\relay-contract`, branch `main`, initially clean.
- Accepted M1C HEAD: `35422d98da34b40d8fe7c517e92c2cc07c69b55b`; starting remote main matched it. Existing origin `https://github.com/ADITHYA-SANJEEVI/relay-contract.git` was inspected as private.
- Pre-edit baselines: M1C **25 passed in 202.08s**; M1B **37 passed in 197.29s**; combined M1A/M0 **134 passed in 25.60s** (122 persistence + 12 infrastructure/storage). No failures/skips/xfails. Evidence and repository agreed before edits.
- Python 3.12.10, real Compose PostgreSQL 18.6 and pinned M0 MinIO. API processes authenticate as `relay_runtime`; storage gateway retains its separate non-admin runtime credential. No SQLite or mocked lock/store correctness path.
- Normative ownership, schema, migrations and publication module are unchanged. No dependency addition or lockfile change.

## Implementation and transaction boundaries

`POST /workers/{session}/heartbeat`, `/drain`, `/stop` and `POST /attempts/{id}/renew` are authenticated real HTTP endpoints. Sequences are canonical decimal strings bounded to nonnegative PostgreSQL bigint, including the maximum 9223372036854775807. Negative, oversized, leading-zero, numeric and boolean sequences reject 422; unknown fields reject. GET attempt includes durable renewal sequence/response for reconciliation.

Renew authenticates first without retaining a connection, then locks **job → partition → attempt**, samples exactly one `clock_timestamp()` after the final lock and checks exact linked job/partition/current generation/latest attempt/owner/ACTIVE state and strict lease/hard-deadline inequalities. Higher sequence writes `min(t + lease_seconds, hard_deadline_at)`, fingerprint, cached response and LEASE_RENEWED in one transaction. Equal exact repeat returns its cached logical response only after fresh live validation, without another event/extension. Equal changed fingerprint rejects idempotency_conflict; lower returns applied=false/current lease. Sequence zero initially ignores. Expired requests reject before cached acknowledgement. No renewal changes claimed_at, owner, generation or hard deadline. A forced real event CHECK abort rolls the complete renewal back, returning 503/not_committed; removing that test-only CHECK permits the same sequence.

Heartbeat locks only the worker row. Higher sequence records fresh DB time; equal/lower preserves last_seen_at. FRESH means DB time minus last_seen_at <30 seconds; the test observes SUSPECT after a local telemetry timestamp fixture then higher-sequence FRESH. No heartbeat durable events or lease mutations. Drain/stop lock only the worker domain, shared with claim's worker-state serialization. Drain denies claims and permits active renewal/publication. Stop requires no ACTIVE attempt, including expired but unsettled ownership. Lifecycle event sequence advances once per transition. Process exit does not imply STOPPED.

The existing singleton scheduler, job/partition claim locks, empty request hash and immutable receipts remain. There is no Python mutex, SKIP LOCKED, recovery, failure endpoint, automatic attempt retry or expiry settlement. Structured logs distinguish renew applied/ignored/rejected, heartbeat applied/ignored, drain/stop, claim claimed/replay/no-work and database contention/unknown outcomes without credential values.

## Heartbeat and lifecycle observed state

```json
{
  "duplicate_seen": {
    "last_heartbeat_seq": 5,
    "last_seen_at": "2026-10-02T09:28:46.006195+00:00",
    "next_event_seq": 2,
    "session_id": "4e72c6ee-fab5-44b9-a024-72b0acf14379",
    "state": "REGISTERED",
    "stopped_at": null
  },
  "events": [
    {
      "details": {},
      "occurred_at": "2026-10-02T09:28:45.595848+00:00",
      "request_id": null,
      "seq": 1,
      "session_id": "4e72c6ee-fab5-44b9-a024-72b0acf14379",
      "type": "WORKER_REGISTERED"
    },
    {
      "details": {
        "from_state": "REGISTERED",
        "to_state": "DRAINING"
      },
      "occurred_at": "2026-10-02T09:28:46.174334+00:00",
      "request_id": null,
      "seq": 2,
      "session_id": "4e72c6ee-fab5-44b9-a024-72b0acf14379",
      "type": "WORKER_DRAINING"
    },
    {
      "details": {
        "from_state": "DRAINING",
        "to_state": "STOPPED"
      },
      "occurred_at": "2026-10-02T09:28:46.435875+00:00",
      "request_id": null,
      "seq": 3,
      "session_id": "4e72c6ee-fab5-44b9-a024-72b0acf14379",
      "type": "WORKER_STOPPED"
    }
  ],
  "heartbeat": {
    "applied": true,
    "db_time": "2026-10-02T09:28:46.006195+00:00",
    "last_heartbeat_seq": "5",
    "last_seen_at": "2026-10-02T09:28:46.006195+00:00",
    "liveness": "FRESH",
    "session_id": "4e72c6ee-fab5-44b9-a024-72b0acf14379",
    "state": "REGISTERED"
  },
  "stopped": {
    "session_id": "4e72c6ee-fab5-44b9-a024-72b0acf14379",
    "state": "STOPPED",
    "stopped_at": "2026-10-02T09:28:46.435875+00:00"
  }
}
```

The active owner returned 409 on stop; repeated drain returned the same DRAINING result; a new claim rejected worker_draining. Renewal and fenced completion succeeded while DRAINING. After settlement stop succeeded and repeated stop/drain preserved STOPPED/timestamp. Worker events were exactly REGISTERED, DRAINING, STOPPED, sequence 1–3. Stopped telemetry did not reopen the state. Idle REGISTERED→STOPPED was tested separately.

## Renewal timeline and duplicate sequencing

```json
{
  "expired": "2026-10-02T09:29:30.206631+00:00",
  "first": {
    "applied": true,
    "db_time": "2026-10-02T09:29:30.365486+00:00",
    "hard_deadline_at": "2026-10-02T09:39:30.206630+00:00",
    "lease_expires_at": "2026-10-02T09:30:00.365486+00:00",
    "sequence": "2"
  },
  "lower": {
    "applied": false,
    "db_time": "2026-10-02T09:29:30.448134+00:00",
    "hard_deadline_at": "2026-10-02T09:39:30.206630+00:00",
    "lease_expires_at": "2026-10-02T09:30:00.365486+00:00",
    "sequence": "2"
  },
  "original_lease": "2026-10-02T09:30:00.206630+00:00",
  "second": {
    "applied": true,
    "db_time": "2026-10-02T09:29:30.513905+00:00",
    "hard_deadline_at": "2026-10-02T09:39:30.206630+00:00",
    "lease_expires_at": "2026-10-02T09:30:00.513905+00:00",
    "sequence": "3"
  }
}
```

```json
{
  "renewal_events": 1,
  "response": {
    "applied": true,
    "db_time": "2026-10-02T09:29:37.567043+00:00",
    "hard_deadline_at": "2026-10-02T09:39:36.130057+00:00",
    "lease_expires_at": "2026-10-02T09:30:07.567043+00:00",
    "sequence": "1"
  },
  "waiting_backends": [
    {
      "pid": 165064,
      "wait_event": "tuple"
    },
    {
      "pid": 165053,
      "wait_event": "transactionid"
    }
  ]
}
```

Sequence 2 extended the original lease exactly from its DB sample plus 30 seconds. Its identical replay preserved the entire cached response; sequence 1 returned applied=false/current lease; equal sequence with generation changed rejected 409/idempotency_conflict without mutation. Sequence 3 extended normally; exactly two renewal events committed. After the test-only lease-shortening fixture, sequences 3,4,1 all rejected lease_expired, heartbeat could not revive ownership, and ACTIVE/stop-busy remained unsettled. The immutable hard deadline was compared unchanged.

Two independent HTTP renewal clients were observed waiting on separate PostgreSQL backends at a held job lock. Same sequence/body produced identical cached results and exactly one LEASE_RENEWED event/time, proving serialization rather than a Python mutex.

## T16 authoritative lock expiry and exact boundaries

```json
[
  {
    "deadline": "2026-10-02T09:29:50.235336+00:00",
    "entered": "2026-10-02T09:29:49.702052+00:00",
    "lock": "job",
    "release": "2026-10-02T09:29:50.238718+00:00",
    "status": 409,
    "waiting_backends": [
      {
        "pid": 165115,
        "wait_event": "transactionid"
      }
    ]
  },
  {
    "deadline": "2026-10-02T09:29:57.083482+00:00",
    "entered": "2026-10-02T09:29:56.580628+00:00",
    "lock": "partition",
    "release": "2026-10-02T09:29:57.087268+00:00",
    "status": 409,
    "waiting_backends": [
      {
        "pid": 165148,
        "wait_event": "transactionid"
      }
    ]
  },
  {
    "deadline": "2026-10-02T09:30:03.856146+00:00",
    "entered": "2026-10-02T09:30:03.307699+00:00",
    "lock": "attempt",
    "release": "2026-10-02T09:30:03.857049+00:00",
    "status": 409,
    "waiting_backends": [
      {
        "pid": 165179,
        "wait_event": "transactionid"
      }
    ]
  }
]
```

Each fixture shortened only its mutable lease under job→partition→attempt locks, then held the selected authoritative row. pg_stat_activity in AUTOCOMMIT observed a real runtime backend waiting while DB time was still before expiry. Only the necessary DB-clock wait crossed the deadline; release followed, and every HTTP renewal returned 409/lease_expired. The attempt remained ACTIVE with sequence 0 and no renewal event. The final-attempt-lock case specifically proves the time sample cannot precede that blocking lock.

Two exact-boundary cases evaluate the production canonical renewal predicate with actual locked PostgreSQL rows and t equal to the stored lease/hard timestamp, and check PostgreSQL's strict comparison returns false. HTTP expiry tests independently cross real DB deadlines. No claim is made that network arrival can be scheduled to a particular microsecond. M1C's unchanged conditional SQL boundary/linearization tests also pass.

## Immutable hard deadline, exact cap and no bypass

```json
{
  "artifact_status": "VERIFIED",
  "claim": {
    "attempt_id": "2eb7fc72-b53a-4218-a702-24c1679c36fc",
    "claimed_at": "2026-10-02T09:30:20.476607+00:00",
    "generation": "1",
    "hard_deadline_at": "2026-10-02T09:31:20.476607+00:00",
    "job_id": "64fadc89-f02c-4109-9ae6-11e007c4b5cb",
    "lease_expires_at": "2026-10-02T09:31:20.476607+00:00",
    "partition_id": "766f263b-13ac-4fc3-ae5d-867a4f07ff16",
    "worker_session_id": "48ae490d-fd0f-407f-8ce4-eb164c0a0401"
  },
  "crossed": "2026-10-02T09:31:20.480156+00:00",
  "publication_status": 409,
  "renewals": [
    {
      "applied": true,
      "db_time": "2026-10-02T09:30:20.742074+00:00",
      "hard_deadline_at": "2026-10-02T09:31:20.476607+00:00",
      "lease_expires_at": "2026-10-02T09:31:20.476607+00:00",
      "sequence": "1"
    },
    {
      "applied": true,
      "db_time": "2026-10-02T09:30:20.791259+00:00",
      "hard_deadline_at": "2026-10-02T09:31:20.476607+00:00",
      "lease_expires_at": "2026-10-02T09:31:20.476607+00:00",
      "sequence": "2"
    },
    {
      "applied": true,
      "db_time": "2026-10-02T09:31:19.008210+00:00",
      "hard_deadline_at": "2026-10-02T09:31:20.476607+00:00",
      "lease_expires_at": "2026-10-02T09:31:20.476607+00:00",
      "sequence": "3"
    }
  ]
}
```

The job was submitted with the valid minimum **60-second** hard policy and a 60-second lease, never increased for test convenience. Real claim-time/hard-deadline fields were never edited. Renewal 3 occurs approximately 1.5 seconds before the actual hard deadline and caps exactly at it; earlier renewals also cap. The harness waits through the real lifetime. At/after hard expiry, latest duplicate/higher/lower renewal all reject 409, higher heartbeat adds no ownership, and claim replay retains the original receipt/generation/lease. A real already-VERIFIED immutable artifact still fails complete with lease_expired; accepted_results remains empty. ACTIVE is deliberately not settled.

## T06 claim idempotency and supported scope/hash semantics

```json
{
  "original": {
    "attempt_id": "bde0a8dc-1a84-487a-a63c-5f9ee7deb177",
    "claimed_at": "2026-10-02T09:31:27.511262+00:00",
    "generation": "1",
    "hard_deadline_at": "2026-10-02T09:41:27.511262+00:00",
    "job_id": "dd0b2fea-43a0-4ebc-a0be-cb28812dc3ca",
    "lease_expires_at": "2026-10-02T09:31:57.511262+00:00",
    "partition_id": "db355789-e0ad-4cd8-80b2-8e7ff9da33e5",
    "worker_session_id": "6cfd7d5f-b3e5-4aa1-a98b-e812a501b661"
  },
  "replay": {
    "attempt_id": "bde0a8dc-1a84-487a-a63c-5f9ee7deb177",
    "claimed_at": "2026-10-02T09:31:27.511262+00:00",
    "generation": "1",
    "hard_deadline_at": "2026-10-02T09:41:27.511262+00:00",
    "job_id": "dd0b2fea-43a0-4ebc-a0be-cb28812dc3ca",
    "lease_expires_at": "2026-10-02T09:31:57.511262+00:00",
    "partition_id": "db355789-e0ad-4cd8-80b2-8e7ff9da33e5",
    "replay": true,
    "worker_session_id": "6cfd7d5f-b3e5-4aa1-a98b-e812a501b661"
  },
  "request_hash": "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
  "scopes": [
    "worker:6cfd7d5f-b3e5-4aa1-a98b-e812a501b661:claim",
    "worker:0ff125ca-a0da-4e99-86be-dc00ba6cb9da:claim"
  ],
  "waiting_backends": [
    {
      "pid": 165515,
      "wait_event": "transactionid"
    },
    {
      "pid": 165525,
      "wait_event": "tuple"
    }
  ]
}
```

Two independent clients race the same worker/key under a PostgreSQL scheduler barrier: 201/200, same attempt/gen/claimed_at/original lease, one receipt and one claim event set. Another key while ACTIVE rejects worker_busy without a new attempt. The empty body's canonical SHA-256 is inspected in the durable receipt. An invented field rejects validation rather than fabricating supported conflict semantics. The real receipt reader rejects a mismatched hash against the stored record. The same key in another worker's distinct scope can claim the separate READY partition, proving keys are scoped rather than global; both partitions remain generation 1 with one ACTIVE owner each.

## T12: 32 independently registered sessions race one partition

```json
{
  "diagnostic_elapsed_seconds": 1.078,
  "generation": 1,
  "owner": "bf3e2565-2aba-43c3-a421-695b923c36ae",
  "receipts": 32,
  "scheduler_next_ticket": 3,
  "sessions": 32,
  "statuses": {
    "201": 1,
    "204": 31,
    "503": 0
  },
  "waiting_backends": [
    {
      "pid": 165632,
      "wait_event": "transactionid"
    },
    {
      "pid": 165630,
      "wait_event": "tuple"
    },
    {
      "pid": 165641,
      "wait_event": "tuple"
    },
    {
      "pid": 165635,
      "wait_event": "tuple"
    },
    {
      "pid": 165633,
      "wait_event": "tuple"
    },
    {
      "pid": 165638,
      "wait_event": "tuple"
    },
    {
      "pid": 165639,
      "wait_event": "tuple"
    },
    {
      "pid": 165546,
      "wait_event": "tuple"
    },
    {
      "pid": 165637,
      "wait_event": "tuple"
    },
    {
      "pid": 165636,
      "wait_event": "tuple"
    },
    {
      "pid": 165631,
      "wait_event": "tuple"
    },
    {
      "pid": 165634,
      "wait_event": "tuple"
    }
  ]
}
```

All 32 sessions are independently registered and use distinct independent HTTP clients, submitted concurrently by a thread pool to the independent API process. Observed PostgreSQL lock waiters have different backend PIDs. The API connection pool and singleton scheduler intentionally serialize decisions; 32 simultaneous executing DB backends or workloads are not claimed. No application/test mutex serializes claims.

Durable inspection proves exactly one ACTIVE attempt, one owner, one RUNNING partition, generation 1, no >1 ACTIVE per session/partition, one claim event set (JOB_SUBMITTED/ATTEMPT_CLAIMED/PARTITION_RUNNING/JOB_RUNNING sequence 1–4), scheduler ticket 3 and receipt count equal to committed 201/204 decisions. A 33rd active registration rejects capacity. Timing is diagnostic only, not a throughput/scaling benchmark.

## T18: committed claim response discarded, then replay

```json
{
  "before_execution": {
    "claimed_at": "2026-10-02T09:32:29.348581+00:00",
    "db_time": "2026-10-02T09:32:29.612237+00:00",
    "hard_deadline_at": "2026-10-02T09:33:29.348581+00:00",
    "last_renew_seq": "0",
    "lease_expires_at": "2026-10-02T09:32:35.348581+00:00",
    "status": "ACTIVE"
  },
  "claim_key": "2af82591-87ab-4ba1-b63e-4d5a4a1b1815",
  "final_attempt": "df2644a2-e1af-4b40-9937-0c477319a03f",
  "final_phase": "ACCEPTED",
  "original": {
    "attempt_id": "df2644a2-e1af-4b40-9937-0c477319a03f",
    "claimed_at": "2026-10-02T09:32:29.348581+00:00",
    "generation": "1",
    "hard_deadline_at": "2026-10-02T09:33:29.348581+00:00",
    "job_id": "1ca57b85-846b-4c33-bc33-719e9bf30ccd",
    "lease_expires_at": "2026-10-02T09:32:35.348581+00:00",
    "partition_id": "600ef7a7-686e-4a67-a996-fc3ba37c3e97",
    "worker_session_id": "00caa2eb-ed4b-487f-95ce-61507e6f8e3c"
  },
  "replay": {
    "attempt_id": "df2644a2-e1af-4b40-9937-0c477319a03f",
    "claimed_at": "2026-10-02T09:32:29.348581+00:00",
    "generation": "1",
    "hard_deadline_at": "2026-10-02T09:33:29.348581+00:00",
    "job_id": "1ca57b85-846b-4c33-bc33-719e9bf30ccd",
    "lease_expires_at": "2026-10-02T09:32:35.348581+00:00",
    "partition_id": "600ef7a7-686e-4a67-a996-fc3ba37c3e97",
    "replay": true,
    "worker_session_id": "00caa2eb-ed4b-487f-95ce-61507e6f8e3c"
  }
}
```

```json
{
  "child_started": false,
  "current_lease": "2026-10-02T09:32:45.078430+00:00",
  "original": {
    "attempt_id": "67eba6df-4aea-488c-9c23-df0e526923db",
    "claimed_at": "2026-10-02T09:32:45.078429+00:00",
    "generation": "1",
    "hard_deadline_at": "2026-10-02T09:33:45.078429+00:00",
    "job_id": "9f15fc6c-c44e-4459-a6bc-36c92f87ddd7",
    "lease_expires_at": "2026-10-02T09:32:51.078429+00:00",
    "partition_id": "39c10614-d24b-4739-868d-66c6b07c959b",
    "worker_session_id": "49affa51-3e83-4b0c-bc29-e0babc1a8ac2"
  },
  "replay": {
    "attempt_id": "67eba6df-4aea-488c-9c23-df0e526923db",
    "claimed_at": "2026-10-02T09:32:45.078429+00:00",
    "generation": "1",
    "hard_deadline_at": "2026-10-02T09:33:45.078429+00:00",
    "job_id": "9f15fc6c-c44e-4459-a6bc-36c92f87ddd7",
    "lease_expires_at": "2026-10-02T09:32:51.078429+00:00",
    "partition_id": "39c10614-d24b-4739-868d-66c6b07c959b",
    "replay": true,
    "worker_session_id": "49affa51-3e83-4b0c-bc29-e0babc1a8ac2"
  },
  "result": {
    "error_code": "claim_replay_not_live",
    "phase": "WORKER_ERROR"
  }
}
```

The localhost test runner performs a real successful claim, discards the committed HTTP response and returns only its same-key retry to the real supervisor. Live replay matches the whole original body except replay=true, and current-before-execution inspection proves original claimed_at/lease and renewal sequence 0. One receipt/attempt/claim event set exists; later operational renewals are distinct operations. Live replay executes/publishes only after current ownership inspection.

The expired case uses a test-only mutable lease fixture after receipt commit, then releases retry. Its historical receipt still returns the original lease/body without regranting ownership. The supervisor queries actual DB time/state, exits claim_replay_not_live, and never starts a child, reserves an artifact or accepts a result. No recovery or generation increment occurs. This tests deterministic response discard, not a comprehensive network-partition model or production automatic claim reconciliation.

## T20 independent process restart and delayed telemetry

```json
{
  "boots": [
    {
      "pid": 21512,
      "session": "023b7c6f-25b9-4076-8a00-cbbf8f7c2820"
    },
    {
      "pid": 2824,
      "session": "f392bf53-c6a9-41d4-994f-3b04b9230992"
    }
  ],
  "new_attempt": "b2b3a32a-5974-4abc-9f47-bc2bfdd85bfd",
  "old_attempt": "d90eb8db-30ec-4e73-9d5c-488fa1b578cd",
  "old_session": {
    "last_heartbeat_seq": 7,
    "last_seen_at": "2026-10-02T09:32:53.467492+00:00",
    "next_event_seq": 2,
    "session_id": "023b7c6f-25b9-4076-8a00-cbbf8f7c2820",
    "state": "REGISTERED",
    "stopped_at": null
  },
  "wrong_owner_status": 403
}
```

Process A registers/heartbeats/claims and intentionally exits without STOP. Process B boots with the same display name, new independently generated UUID/secret and cannot steal A's RUNNING partition (204). B's secret with A's session header returns 401; B's authentic identity renew/complete against A returns 403. A's heartbeat seq7/state/last_seen_at and lease remain unchanged after duplicate/lower telemetry and B's higher telemetry. A stays REGISTERED/ACTIVE, generation 1. A separate newly submitted READY partition can be claimed normally by B under a fresh key. Private test credential binding files remain in ignored cache only and are cleaned with the disposable harness; no secret is printed.

## Supervisor/child and operational renewal

```json
{
  "api_pid": 19040,
  "ready": {
    "child_pid": 4084,
    "credential_environment_present": false
  },
  "result": {
    "accepted_result": {
      "accepted_at": "2026-10-02T09:32:10.258202+00:00",
      "artifact_id": "a3fd99eb-f7dd-4fd1-9eb7-a48a97ffc631",
      "artifact_uri": "s3://relay-m0-contract/jobs/418900ad-8270-44d3-9bc9-93f373471025/partitions/0/attempt-1/a3fd99eb-f7dd-4fd1-9eb7-a48a97ffc631/output.parquet?versionId=c023b95b-5e9f-4b4b-9d7d-77e27d4c7f84",
      "attempt_id": "ae5a0691-308b-43e5-924a-c193d368391d",
      "generation": "1",
      "object_version": "c023b95b-5e9f-4b4b-9d7d-77e27d4c7f84",
      "partition_id": "f4a0cda8-bc11-433d-91b6-b3f7b92c476e",
      "sha256": "3168790fabecf3e52025c091ffe9775b8e77afeafd384ebe31db9a3cee2d3a78",
      "size_bytes": "2092"
    },
    "artifact_id": "a3fd99eb-f7dd-4fd1-9eb7-a48a97ffc631",
    "attempt_id": "ae5a0691-308b-43e5-924a-c193d368391d",
    "child_credential_environment_present": false,
    "child_pid": 4084,
    "counters": {
      "input_rows": 12,
      "invalid_reasons": {
        "invalid_record_id": 1,
        "invalid_region": 1
      },
      "invalid_rows": 2,
      "valid_rows": 10
    },
    "elapsed_seconds": 9.531,
    "generation": "1",
    "job_id": "418900ad-8270-44d3-9bc9-93f373471025",
    "job_status": "SUCCEEDED",
    "object_version": "c023b95b-5e9f-4b4b-9d7d-77e27d4c7f84",
    "original_lease_expires_at": "2026-10-02T09:32:07.962525+00:00",
    "partition_id": "f4a0cda8-bc11-433d-91b6-b3f7b92c476e",
    "phase": "ACCEPTED",
    "renewals": [
      {
        "applied": true,
        "db_time": "2026-10-02T09:32:04.222250+00:00",
        "hard_deadline_at": "2026-10-02T09:33:01.962525+00:00",
        "lease_expires_at": "2026-10-02T09:32:10.222250+00:00",
        "sequence": "1"
      },
      {
        "applied": true,
        "db_time": "2026-10-02T09:32:06.294005+00:00",
        "hard_deadline_at": "2026-10-02T09:33:01.962525+00:00",
        "lease_expires_at": "2026-10-02T09:32:12.294005+00:00",
        "sequence": "2"
      },
      {
        "applied": true,
        "db_time": "2026-10-02T09:32:08.361136+00:00",
        "hard_deadline_at": "2026-10-02T09:33:01.962525+00:00",
        "lease_expires_at": "2026-10-02T09:32:14.361136+00:00",
        "sequence": "3"
      }
    ],
    "sha256": "3168790fabecf3e52025c091ffe9775b8e77afeafd384ebe31db9a3cee2d3a78",
    "size_bytes": "2092",
    "worker_pid": 20596,
    "worker_session_id": "bf1c35df-8aed-4bf6-ae76-20b89a180a97"
  }
}
```

```json
{
  "accepted_count": 0,
  "artifact_count": 0,
  "child_pid": 11248,
  "result": {
    "error_code": "renewal_authority_lost",
    "phase": "WORKER_ERROR"
  },
  "supervisor_launcher_pid": 21492
}
```

Supervisor and child have different actual OS PIDs. A monotonic supervisor-owned maintenance thread uses its own HTTP client for renewal and separate heartbeat; the CPU workload runs in a child with only local task paths/OS essential environment. No API/session/bootstrap/operator/DB/store credential enters the child's environment. A controlled seven-second CPU duration exceeds the six-second initial lease; advertised cadence is two seconds. Default 30-second jobs retain the frozen ten-second cadence. Each successful result is still reserved, uploaded, verified and accepted through the unchanged M1C fence, with exact-version decoded output matching the independent serial oracle.

Definite HTTP renew rejection after child readiness sets authority loss, terminates the child tree best-effort, reports no ACCEPTED result and commits no artifact reservation or acceptance. Tests query actual child process liveness and durable rows/events, and verify the API logged renew/lease_expired. Windows venv launcher PIDs can differ from actual Python PIDs. Termination targets only the launched workload tree via [taskkill /T](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/taskkill); pipe EOF is drained to close inherited descendant handles before removing temporary task files. Normal exit leaves artifact/publication in the supervisor.

The local lease estimate uses a monotonic timestamp preceding current DB observation. Uncertain renewal transport/503 retries preserve the same sequence and its first-send time; a cached old DB-time acknowledgement cannot add local authority. DB predicates remain authoritative, and a local deadline is conservative. Completion stops maintenance before ACTIVE settlement to avoid a renewal racing successful terminal state. No automatic attempt retry follows authority loss.

## Three concurrent normal workers

```json
{
  "accepted_count": 3,
  "api_pid": 2972,
  "initial_active": 3,
  "workers": [
    {
      "accepted_result": {
        "accepted_at": "2026-10-02T09:33:13.454195+00:00",
        "artifact_id": "a2686a04-e510-4543-aa27-3d29bef29921",
        "artifact_uri": "s3://relay-m0-contract/jobs/9caa715a-fa11-4bd1-8913-65cc3cfcd433/partitions/0/attempt-1/a2686a04-e510-4543-aa27-3d29bef29921/output.parquet?versionId=69f5d2c9-24c7-4d36-b5da-66059d49afa3",
        "attempt_id": "d0104651-9027-4620-a290-38dcd255399d",
        "generation": "1",
        "object_version": "69f5d2c9-24c7-4d36-b5da-66059d49afa3",
        "partition_id": "61513046-20b9-4253-b9b8-ce76625ca067",
        "sha256": "3168790fabecf3e52025c091ffe9775b8e77afeafd384ebe31db9a3cee2d3a78",
        "size_bytes": "2092"
      },
      "attempt_id": "d0104651-9027-4620-a290-38dcd255399d",
      "child_credential_environment_present": false,
      "child_pid": 12552,
      "generation": "1",
      "original_lease_expires_at": "2026-10-02T09:33:10.275202+00:00",
      "partition_id": "61513046-20b9-4253-b9b8-ce76625ca067",
      "renewals": [
        {
          "applied": true,
          "db_time": "2026-10-02T09:33:06.499040+00:00",
          "hard_deadline_at": "2026-10-02T09:34:04.275202+00:00",
          "lease_expires_at": "2026-10-02T09:33:12.499040+00:00",
          "sequence": "1"
        },
        {
          "applied": true,
          "db_time": "2026-10-02T09:33:08.590016+00:00",
          "hard_deadline_at": "2026-10-02T09:34:04.275202+00:00",
          "lease_expires_at": "2026-10-02T09:33:14.590016+00:00",
          "sequence": "2"
        },
        {
          "applied": true,
          "db_time": "2026-10-02T09:33:10.649382+00:00",
          "hard_deadline_at": "2026-10-02T09:34:04.275202+00:00",
          "lease_expires_at": "2026-10-02T09:33:16.649382+00:00",
          "sequence": "3"
        },
        {
          "applied": true,
          "db_time": "2026-10-02T09:33:12.712814+00:00",
          "hard_deadline_at": "2026-10-02T09:34:04.275202+00:00",
          "lease_expires_at": "2026-10-02T09:33:18.712814+00:00",
          "sequence": "4"
        }
      ],
      "worker_pid": 20880,
      "worker_session_id": "84a08d65-027d-4c56-a483-f15ebbafbd5d"
    },
    {
      "accepted_result": {
        "accepted_at": "2026-10-02T09:33:13.361152+00:00",
        "artifact_id": "e5c51e38-c8e5-4ca4-a29d-af534fffdb8e",
        "artifact_uri": "s3://relay-m0-contract/jobs/9caa715a-fa11-4bd1-8913-65cc3cfcd433/partitions/2/attempt-1/e5c51e38-c8e5-4ca4-a29d-af534fffdb8e/output.parquet?versionId=40e94128-b62b-48c3-9cfe-d7c869d948c7",
        "attempt_id": "f880a022-ab30-4750-8819-4ee76997a55f",
        "generation": "1",
        "object_version": "40e94128-b62b-48c3-9cfe-d7c869d948c7",
        "partition_id": "31ed34da-3e7f-477a-9ed5-77a90ee7ccae",
        "sha256": "3f1940ba3b7a32cfa743f4befb8739ed6062335c5cee592a0f17058806d9f0cf",
        "size_bytes": "2087"
      },
      "attempt_id": "f880a022-ab30-4750-8819-4ee76997a55f",
      "child_credential_environment_present": false,
      "child_pid": 18616,
      "generation": "1",
      "original_lease_expires_at": "2026-10-02T09:33:10.582540+00:00",
      "partition_id": "31ed34da-3e7f-477a-9ed5-77a90ee7ccae",
      "renewals": [
        {
          "applied": true,
          "db_time": "2026-10-02T09:33:06.754401+00:00",
          "hard_deadline_at": "2026-10-02T09:34:04.582540+00:00",
          "lease_expires_at": "2026-10-02T09:33:12.754401+00:00",
          "sequence": "1"
        },
        {
          "applied": true,
          "db_time": "2026-10-02T09:33:08.854764+00:00",
          "hard_deadline_at": "2026-10-02T09:34:04.582540+00:00",
          "lease_expires_at": "2026-10-02T09:33:14.854764+00:00",
          "sequence": "2"
        },
        {
          "applied": true,
          "db_time": "2026-10-02T09:33:10.930953+00:00",
          "hard_deadline_at": "2026-10-02T09:34:04.582540+00:00",
          "lease_expires_at": "2026-10-02T09:33:16.930953+00:00",
          "sequence": "3"
        },
        {
          "applied": true,
          "db_time": "2026-10-02T09:33:12.987695+00:00",
          "hard_deadline_at": "2026-10-02T09:34:04.582540+00:00",
          "lease_expires_at": "2026-10-02T09:33:18.987695+00:00",
          "sequence": "4"
        }
      ],
      "worker_pid": 27128,
      "worker_session_id": "7953053d-b769-4b59-874c-5fd9e4221d04"
    },
    {
      "accepted_result": {
        "accepted_at": "2026-10-02T09:33:13.540033+00:00",
        "artifact_id": "dfc8e36f-f2d4-4fe0-a469-158ff5553b04",
        "artifact_uri": "s3://relay-m0-contract/jobs/9caa715a-fa11-4bd1-8913-65cc3cfcd433/partitions/1/attempt-1/dfc8e36f-f2d4-4fe0-a469-158ff5553b04/output.parquet?versionId=b093fbb4-2db9-47ed-987d-d99de3ddff13",
        "attempt_id": "7cecc3c0-1011-4aae-a50d-726bd8c7e490",
        "generation": "1",
        "object_version": "b093fbb4-2db9-47ed-987d-d99de3ddff13",
        "partition_id": "ec5d4fea-a669-424b-8ffa-5816749bb3fc",
        "sha256": "ff2d455a4138c75dcb166e8d8eb6035b423e7417855b86a649b9e6ac617c97f3",
        "size_bytes": "2145"
      },
      "attempt_id": "7cecc3c0-1011-4aae-a50d-726bd8c7e490",
      "child_credential_environment_present": false,
      "child_pid": 5792,
      "generation": "1",
      "original_lease_expires_at": "2026-10-02T09:33:10.436755+00:00",
      "partition_id": "ec5d4fea-a669-424b-8ffa-5816749bb3fc",
      "renewals": [
        {
          "applied": true,
          "db_time": "2026-10-02T09:33:06.634623+00:00",
          "hard_deadline_at": "2026-10-02T09:34:04.436755+00:00",
          "lease_expires_at": "2026-10-02T09:33:12.634623+00:00",
          "sequence": "1"
        },
        {
          "applied": true,
          "db_time": "2026-10-02T09:33:08.714855+00:00",
          "hard_deadline_at": "2026-10-02T09:34:04.436755+00:00",
          "lease_expires_at": "2026-10-02T09:33:14.714855+00:00",
          "sequence": "2"
        },
        {
          "applied": true,
          "db_time": "2026-10-02T09:33:10.780495+00:00",
          "hard_deadline_at": "2026-10-02T09:34:04.436755+00:00",
          "lease_expires_at": "2026-10-02T09:33:16.780495+00:00",
          "sequence": "3"
        },
        {
          "applied": true,
          "db_time": "2026-10-02T09:33:12.833583+00:00",
          "hard_deadline_at": "2026-10-02T09:34:04.436755+00:00",
          "lease_expires_at": "2026-10-02T09:33:18.833583+00:00",
          "sequence": "4"
        }
      ],
      "worker_pid": 5276,
      "worker_session_id": "ae8b4bfa-efc8-4b27-b0c4-c896636e8189"
    }
  ]
}
```

A three-partition, 36-row job had three ACTIVE attempts simultaneously, with distinct sessions/processes/partitions and no ownership duplicates. Three child barriers were observed before release, then concurrent controlled CPU work required renewal. All three accepted after their original leases, with one result/partition and exactly three RESULT_ACCEPTED events; the job became SUCCEEDED. Each pinned version was independently read through the integrity path and decoded against its assigned 12-row serial oracle. This is correctness evidence, not a throughput result or global-reduction claim.

## Final verification

The suites below are separate pytest invocations. Each completed against real services with zero failures, skips, xfails or warnings.

| Gate | Passed | Observed duration |
|---|---:|---|
| M2 | 25 | 275.08s (0:04:35) |
| M1C | 25 | 170.99s (0:02:50) |
| M1B | 37 | 156.64s (0:02:36) |
| M1A | 122 | 17.93s |
| M0 | 12 | 3.33s |

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
.\.venv\Scripts\python.exe -m pytest tests/concurrency -q -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/publication -q -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/unit tests/integration -q -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/persistence -q --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/infrastructure tests/storage_contract -q --maxfail=1
.\.venv\Scripts\uv.exe lock --check --offline --cache-dir .cache/uv
```

M1C regressions retain fresh fencing, historical accepted replay after expiry, T05 publication concurrency, T26 linearization, full T01 and runtime/storage authority separation. The only previous test expectation changed is the old M1B renew=404 assertion: M2 now asserts unauthenticated renew=401; fail/cancel stay 404. No substantive former safety assertion was relaxed. `publication.py`/FENCED_UPDATE, schema, migration guards and dependency manifests were compared unchanged. `git diff --check`, compileall, offline lock check and actual local-credential byte scan of tracked/candidate content passed; no credential values were emitted. Existing CRLF normalization notices are Git line-ending notices, not whitespace errors or test warnings.

Development failures were resolved before the final gate: a test assumed Windows launcher PID equalled Python PID; a test collection indentation error was corrected; an empty regex pytest warning was removed; and a real Windows descendant handle race on authority-loss cleanup required process-tree termination plus pipe EOF. Failed development runs are not counted as acceptance evidence. Final logs are ignored local files under `.cache`, with concise observed traces committed here.

One later publication rerun failed during API setup with `ImportError: DLL load failed while importing lib: The handle is invalid` in PyArrow (2 passed, 1 setup error). Its existing pytest settings fixture representation exposed local credential values. `tests/conftest.py` now wraps settings in a dict with redacted repr/str; this changes failure rendering only, without weakening any test. PostgreSQL admin/runtime passwords and operator/bootstrap tokens were rotated in ignored local `.env`; both new DB credentials authenticated successfully, and role privileges/retained state were unchanged. Final API-heavy suites were rerun serially with the same pinned dependencies and fresh redacted settings. No automatic startup retry or skip was added. The intermittent Windows DLL startup failure has not been systematically diagnosed; successful final reruns are the recorded gate, not proof that the host issue can never recur.

A separate runtime-role read at `2026-10-02T09:25:06.773514+00:00` found the original retained M1B attempt `ce849793-0a80-4c7c-9928-2565952223bb` still ACTIVE/generation 1/renew sequence 0, with original lease `2026-10-01T23:36:34.088033+00:00` and hard deadline `2026-10-01T23:46:04.088033+00:00`. Its two-partition job remained RUNNING with zero accepted result for this attempt. M2 did not settle/reassign retained expired ownership.

## Fault control, provenance and limitations

The HTTP/API/worker processes are real and independent. Each test uses a newly allocated UUID-named PostgreSQL database migrated by the trusted migration identity; application actions use only runtime authority. Durable rows are inspected before teardown, then only the allocated DB/cache children are removed. Immutable test object versions remain in MinIO; retained M0/application volumes/rows are not reset. Test-only lease fixtures mutate the mutable lease under canonical lock order, never immutable claim time/hard deadline; hard-deadline evidence waits real time without field changes. The rejecting CHECK is installed only in the disposable test DB and removed explicitly. Controlled child duration/file barriers, response discard and restart probes exist only under tests/concurrency with localhost configuration and internal injection; production CLI/API exposes no fault-control endpoint.

Expired attempts deliberately remain ACTIVE, partitions RUNNING and generations unchanged. Such attempts also prevent STOP, and vanished registered sessions still count toward configured capacity until explicit legal lifecycle settlement. No recovery/reaper, EXPIRED settlement, reassignment, bounded attempt retry policy, failure/cancel endpoint or generation 4→5 proof exists. These remain later authorized work. Worker claim/publication transport reconciliation is not a complete automated operational loop; retained orphan objects have no garbage collection. Child termination is best-effort local control; DB fencing supplies safety even if CPU termination fails. Exact arbitrary network partitions, host crashes and scaling limits have not been comprehensively tested. No benchmark or production-readiness claim is made.

M2 establishes tested concurrent ownership, renewable live leases with an immutable absolute deadline, monotonic session telemetry/lifecycle, historical claim replay safety and independently supervised child execution, while retaining at most one accepted result per immutable partition. It does not establish exactly-once execution or complete Relay V1 fault tolerance. Stop here; M3 is not started.
