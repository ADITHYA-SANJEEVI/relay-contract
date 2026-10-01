# REST contract

Base `/v1`. JSON except streamed artifact bytes. UTC RFC3339 timestamps, UUID strings, bigint counters encoded as decimal strings, SHA-256 lowercase hex. Unknown fields rejected. Default page size 100, maximum 500. Errors: `{error:{code,message,retryable,outcome,request_id,details}}`; outcome is `rejected`, `not_committed`, or `unknown`. No stack traces, secrets or arbitrary input data in errors/events. 400 malformed, 401 unauthenticated, 403 wrong owner, 404 unknown resource, 409 state/idempotency conflict, 422 invalid data/integrity, 429 capacity, 503 unavailable. A 503 is never proof that a transaction failed to commit.

Local V1 uses an operator token for client actions and separate worker bootstrap credential. Registration binds a per-session credential to a boot UUID; store credential hashes, not plaintext. Credential delivery/retry must use a deterministic client-held session secret or equivalent recoverable registration protocol; baseline is client generates random 256-bit session secret, sends it over local trusted transport, server stores hash and checks exact registration retry. Never log token bodies. Bind services to localhost by default; deployment beyond trusted local network requires TLS and a separate security review, outside V1.

## Client endpoints

| Method/path | Request | Response / semantics |
|---|---|---|
| POST /inputs | Idempotency-Key; metadata `{sha256,size_bytes,media_type,schema_hash}` | 201 reserved input ID, canonical upload URL; same key/body 200, changed body 409 |
| PUT /inputs/{id}/content | Exact bytes; expected hash/size established by reservation | 200 VERIFIED input with version/hash/counts after readback; existing different bytes 409/422; transient 503 leaves reconcilable reservation |
| GET /inputs/{id} | Operator authentication | State, immutable metadata, verification errors |
| POST /jobs | Required Idempotency-Key; contract below | 201 job plus definition hash/status; replay 200 same ID; same key/different definition 409 |
| GET /jobs/{id} | None | Identity, definition_hash, status, timestamps, partition/attempt counts, next_event_seq, partial_result_count, complete |
| POST /jobs/{id}/cancel | `{reason}` bounded 1 KiB | 200 CANCELLED with preserved accepted count; repeated cancel returns original reason/time; terminal SUCCEEDED/FAILED 409 |
| GET /jobs/{id}/partitions | `after_ordinal`, `limit`, optional status | Ordered partition records and next cursor; state, generation, eligible_at, current attempt/lease, terminal error, accepted artifact ID |
| GET /jobs/{id}/events | `after_seq`, `limit` | Ordered durable events, next cursor; polling allowed; no websocket dependency |
| GET /jobs/{id}/results | `after_ordinal`, `limit` | Accepted manifests only, job status and complete flag; partial on failed/cancelled jobs |
| GET /artifacts/{id}/content | Operator or owning worker authorization | Exact verified version bytes with SHA-256 header; only accepted artifacts for ordinary job consumers; integrity failure explicit |

Submission body:

```json
{
  "workload": {"name":"normalize_aggregate", "version":"1", "digest":"sha256:<pinned-digest>"},
  "inputs": [{"input_ordinal":0,"artifact_id":"<verified-input-uuid>"}],
  "partitions": [{"ordinal":0,"slices":[{"input_ordinal":0,"first_row":"0","row_count":"100000"}]}],
  "parameters": {"normalization_version":"1"},
  "policy": {"max_attempts":5,"lease_seconds":30,"max_attempt_seconds":600},
  "parent_job_id": null
}
```

Ordinal values must be contiguous starting at zero. API canonicalizes validated JSON and computes definition_hash; the client cannot dictate it. Defaults materialize before hashing. Size and manifest checks precede transaction creation; immutable input references are rechecked inside submission transaction. All partitions are visible together or none are. Submission receipts scoped to operator identity and endpoint persist for V1 lifetime. Client retries use the same key and exact semantic body.

## Worker endpoints

Renewal, fresh owner failure, live-attempt artifact reservation and new completion require [live attempt ownership](SPEC.md#live-attempt-ownership--canonical-predicate), including job RUNNING. Exact historical accepted completion replay remains valid after cancellation. Individual endpoints may impose additional checks, not weaken that predicate.

| Method/path | Request | Response / idempotency |
|---|---|---|
| POST /workers/register | `{session_id,session_secret,display_name,deployment_workload_digest}` plus bootstrap auth | 201 REGISTERED; exact retry 200; changed binding 409; session_secret never returned/logged |
| POST /workers/{session}/heartbeat | `{sequence}` under session credential | State, DB time, derived liveness; same/lower seq ignored without extending last_seen_at |
| POST /workers/{session}/drain | Empty | 200 DRAINING; existing active work may settle; no new claims |
| POST /workers/{session}/stop | Empty | 200 STOPPED if no ACTIVE attempt; otherwise 409 busy; repeat 200 |
| POST /workers/{session}/claim | Required Idempotency-Key, empty body | 201 claim contract below; exact retry 200 receipt; 204 no eligible work (repeat key repeats 204); busy/state mismatch 409 |
| POST /attempts/{id}/renew | `{job_id,partition_id,generation,sequence}` | 200 deadline, DB time, applied flag; current live ownership required; no duplicate extension |
| POST /attempts/{id}/artifact | `{job_id,partition_id,generation,sha256,size_bytes,schema_hash}` | 201 reservation ID/canonical upload URL; exact repeat 200; changed fingerprint 409 |
| PUT /artifacts/{id}/content | Raw Parquet bytes with worker credential | 200 VERIFIED metadata after store readback; idempotent exact reservation; no authority implied |
| GET /attempts/{id} | Owning worker | Status, current generation, lease, artifact, accepted result if any; reconciliation after uncertain responses |
| POST /attempts/{id}/complete | `{request_id,job_id,partition_id,generation,artifact_id,artifact_uri,sha256}` | 201 newly accepted, 200 identical past acceptance; state/lease/generation conflicts 409 |
| POST /attempts/{id}/fail | `{job_id,partition_id,generation,code,detail}` | 200 recorded failure/disposition; fingerprint-identical repeat returns same; conflicting terminal request 409 |

Claim response includes job_id, partition_id, ordinal, attempt_id, generation, worker_session_id, claimed_at, lease_expires_at, hard_deadline_at, renew_after_seconds, workload digest, parameters and immutable input slices. A replay may describe a now-terminal attempt; response includes replay=true. Worker must query/renew before executing a replayed claim and must never treat the receipt as a new lease. Poll when idle using new keys; backoff 250ms→2s for empty queue with bounded jitter outside deterministic tests. Session supervisor keeps renewals separate from workload child process and kills child best-effort when renewal loses authority.

Complete response includes accepted_result `{partition_id,attempt_id,generation,artifact_id,sha256,accepted_at}`, replay flag and current job status. The URI must match the gateway's registered canonical identity; users cannot supply a different bucket/key or external HTTP URL. On exact accepted replay the job may now be CANCELLED; historical acceptance still returns 200.

Conflict codes: stale_generation, lease_expired, attempt_terminal, job_cancelled, terminal_job, result_conflict, artifact_not_verified, artifact_identity_mismatch, idempotency_conflict, worker_busy, worker_draining. A failed validity predicate does not consume another attempt. Request_id is reused after transport uncertainty; a deliberate new publication attempt after an earlier known rejection gets a new request_id.

## Observability

Post-acceptance integrity failures on exact pinned-version reads are explicit errors with structured logs and appropriate metrics. Accepted metadata is unchanged; another object is never substituted and a terminal partition is not automatically recomputed. Durable, deduplicated, queryable integrity-incident persistence and a query API for it are deferred beyond V1.

`GET /health/live` reports process liveliness; `GET /health/ready` checks DB connection, migration version and store capability readiness. Liveness does not depend on stores. `GET /metrics` uses low-cardinality labels: status, operation, workload version and rejection reason; never job/partition IDs as metric labels.

Durable counters derive from events/rows: jobs submitted/succeeded/failed/cancelled, attempts claimed/failed/expired, retries (claims with generation>1), reassignments after expiry, accepted publications, distinct rejected publication requests, stale-generation rejections. Gauges: jobs by status, partitions by status, eligible/delayed queue depth, active workers and attempts, oldest eligible age, orphan bytes. Histograms from measured operations: execution time, publication time, DB lock wait, queue wait, recovery time. HTTP request counters are process metrics and may reset; do not equate them to durable business counts. Lease expirations count settled expiry events, with observed expired-but-unsettled gauge separately.

JSON logs include timestamp, severity, component, operation, request_id, job_id, partition_id, attempt_id, generation, worker_session_id, event_seq when committed, duration_ms, error_code. State events commit with mutations; worker telemetry and transport logs do not pretend to be durable events. Auditable order is per job, not a deterministic order across unrelated concurrent jobs.
