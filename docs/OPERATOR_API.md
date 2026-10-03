# R1 operator visibility contract

Revision `r1_operator_visibility_v1`. The additive `/v1/operator` surface is
observational. PostgreSQL remains the sole execution and accepted-result authority.
Duplicate computation may occur; at most one accepted result exists per immutable
partition. These routes do not change the M1-M3 transition protocol.

## Common request and observation rules

All routes below are **GET** and require the existing local operator bearer token.
Worker session credentials cannot authorize them. There is no new browser cookie,
pairing, viewer role, production authentication or CORS adapter. Preserve the
localhost/trusted-installation boundary in [API.md](API.md). Responses include
`Cache-Control: private, no-store` and the existing `X-Request-Id` header. Unknown
query fields reject 422. UUID parameters require exact UUIDs.

Each response includes `as_of` (one PostgreSQL `clock_timestamp()` sample at the
first SELECT) and `snapshot_scope="request_repeatable_read"`. All database fields
in that response use a single PostgreSQL **READ ONLY, REPEATABLE READ** transaction.
The snapshot is acquired by that first SELECT, not at response delivery. There
are no ownership locks. Independent requests/pages have independent snapshots;
these are not an installation-wide serializable snapshot or a subscription.
Deadlines/countdowns and worker liveness are observations relative to `as_of`.
They do not transition durable state or authorize a worker operation.

Timestamps are UTC RFC3339. UUIDs are strings. Bigint generations, counts, byte
sizes, row ranges, sequences and frontiers are decimal strings; ordinals, version
and bounded policy integers are JSON numbers. Schema details are explicit frozen
Pydantic contracts in `src/relay/operator/models.py` and generated OpenAPI
`/openapi.json`; no persistence rows are returned. Ordinary pages default to 100,
maximum 500, with a `limit+1` continuation probe. All cursors are exclusive. A
null cursor means no further matches **in that request's snapshot and filter**.
Keep the original filter and ordering when requesting continuation. New jobs or
state changes can enter/leave independently refreshed pages. Refresh from the
beginning to discover newer jobs; retain the highest retrieved event sequence
when polling. Never skip events by substituting a frontier for a loaded cursor.

Normal reads never call object storage. The single exception is the explicitly
requested `/artifacts/{id}/verification` route below. Existing consumer
`/v1/jobs/{id}/results` and `/v1/artifacts/{id}/content` retain their original
pinned-content behavior and authorization; neither is replaced by R1.

## Route inventory

Paths in this table are relative to `/v1/operator`. Each response also has the
common observation fields above. Full schemas are listed in the next section.

| GET path | Purpose / parameters and continuation | Response contract | Persisted authority source | Capability | Storage read |
|---|---|---|---|---|---|
| `/capabilities` | Implementation/revision discovery; no parameters | `Capabilities` | `relay_schema_version` plus fixed shipped route manifest | BV12 | No |
| `/jobs` | Catalogue; optional `status`, opaque `cursor`; `limit`; created_at DESC, id DESC; cursor binds both sort fields and status | `JobPage`: items, next_cursor | jobs; partition/attempt/accepted counts derived in SQL | BV01 | No |
| `/jobs/{id}` | Exact current job summary; no parameters | `JobSnapshot`: job | jobs plus scoped row counts | BV01 | No |
| `/jobs/{id}/partitions` | Enriched ordinal page; `after_ordinal=-1` through 4095, `limit`, optional `status`; ordinal ASC | `PartitionPage`: job_id, items, next_cursor | partitions, current generation FK, attempts, artifacts, accepted_results | BV03 | No |
| `/partitions/{id}` | One partition with its complete recorded attempt history; no parameters | `PartitionSnapshot`: partition, attempts, history_complete=true | partitions, all recorded attempts, artifacts, accepted_results | BV03 | No |
| `/partitions/{id}/history` | Alias of partition snapshot for the frozen history deep link; same complete history | `PartitionSnapshot` | Same as partition snapshot | BV03 | No |
| `/attempts/{id}` | Safe direct operator attempt/provenance read; no parameters | `AttemptSnapshot`: attempt | attempts linked to partition/job, optional artifact and accepted relation | BV04 | No |
| `/artifacts/{id}` | Passive provenance of a known accepted or unaccepted output; no parameters | `ArtifactSnapshot`: job_id, ordinal, artifact, accepted_authority, is_accepted_artifact | artifacts, attempts, partitions, accepted_results | BV05 | No |
| `/jobs/{id}/result-metadata` | Accepted manifests; `after_ordinal=-1` through 4095, `limit`; ordinal ASC | `ResultPage`: job_id, job_status, complete, partition_count, partial_result_count, items, next_cursor | accepted_results joined to exact attempt/artifact and partition | BV06 | No |
| `/jobs/{id}/events` | Job-local chronology; `direction=forward` or backward, `after_seq` or `before_seq`, `limit`, optional `partition_id`, `attempt_id`; continuation detailed below | `EventPage` | persisted events and job next_event_seq | BV08 | No |
| `/workers` | Session catalogue; optional `state`, UUID `after_session`, `limit`; session UUID ASC | `WorkerPage`: items, next_cursor | workers and their recorded ACTIVE assignment | BV07 | No |
| `/workers/{id}` | Session identity, lifecycle, liveness and recorded ACTIVE assignment; no parameters | `WorkerSnapshot`: worker | workers and attempts | BV07 | No |
| `/workers/{id}/attempts` | Paged participation across jobs; optional UUID `after_attempt`, `limit`; attempt UUID ASC, not time order | `ParticipationPage`: session_id, items, next_cursor | attempts owned by exact session with job/partition/artifact/authority linkage | BV07 | No |
| `/workers/{id}/events` | Durable register/drain/stop chronology; `after_seq=0`, `limit`; seq ASC | `WorkerEventPage` | worker_events and worker next_event_seq | BV07 | No |
| `/jobs/{id}/definition` | Complete bounded immutable descriptor and pinned input metadata; no parameters | `DefinitionSnapshot` | jobs, job_inputs/input_artifacts, partitions/partition_inputs | BV09 | No |
| `/artifacts/{id}/verification` | Explicit diagnostic of an **accepted** output; no parameters or caller-supplied URI/version/key | `VerificationSnapshot`: artifact snapshot plus independent verification result | accepted_results and committed artifact version/hash/size; then exact object-store bytes | BV05 | **Yes, on demand** |

## Response concepts and authority

`JobSummary` contains id, definition_hash, workload_name/version, recorded status,
created/started/finished times, partition_count, attempt_count, partition_counts
(READY/RUNNING/SUCCEEDED/FAILED/CANCELLED), next_event_seq, partial_result_count
and complete. Counts are scoped to that job; no installation KPI is implied.
Complete is true only for recorded job SUCCEEDED. A FAILED job may retain partial
accepted manifests. No display name, retry aggregate, throughput or host metric
is invented.

`PartitionObservation` contains id, job_id, zero-based ordinal, recorded status,
current generation, eligible_at, created/started/finished times, last_error_code,
latest_attempt (nullable) and accepted_authority. Latest resolves the persisted
current-generation link. A READY retry may have a terminal latest attempt; a
generation-zero partition has none. Partition snapshots include **all** attempts
ordered generation DESC then id, with `history_complete=true`. The accepted
policy caps attempts at ten. An eleventh recorded row is a diagnostic error,
never silently truncated history. Event history is a separate bounded read, not
an unbounded embedded rejection ledger.

`AttemptObservation` contains id, job_id, partition_id, ordinal, generation,
current_generation, worker_session_id, recorded status, claimed_at,
lease_expires_at, hard_deadline_at, last_renew_seq, finished_at, failure_code,
ownership_observation, optional artifact, accepted_authority,
is_accepted_attempt and a correlated events_url. No session credential/hash,
failure_detail, failure fingerprint or renewal-response payload is exposed.
Publication outcome evidence is the accepted relation plus correlated persisted
events; absence of acceptance is not proof of computation failure or a rejected
publication. Durable attempts do not record CPU start/end or every failed send.

Ownership observation is TERMINAL for a non-ACTIVE recorded attempt; otherwise
SUPERSEDED if its generation differs from the partition generation, otherwise
DEADLINE_PASSED when `as_of >= lease_expires_at` or `as_of >= hard_deadline_at`,
otherwise WITHIN_DEADLINES. This describes recorded identity/deadlines and makes
no operational permission promise. ACTIVE past a deadline remains ACTIVE until
the existing settlement protocol commits an outcome.

`accepted_authority` is a discriminated union:

```json
{"status":"NONE"}
```

or:

```json
{
  "status":"ACCEPTED",
  "result":{
    "partition_id":"<uuid>", "attempt_id":"<uuid>", "generation":"5",
    "artifact_id":"<uuid>", "accepted_at":"<UTC timestamp>",
    "publication_fingerprint":"<SHA-256 hex>"
  }
}
```

Every accepted field comes **only** from the immutable `accepted_results` row.
The contract never uses latest attempt, current generation, SUCCEEDED status,
worker report, storage existence or hash equality to reconstruct acceptance.
When inspecting an old attempt/artifact, accepted_authority still identifies the
partition's actual accepted result; is_accepted_attempt/artifact tells whether
the inspected entity participates in it. An expired G4 artifact can remain
VERIFIED while G5 alone is accepted. Different IDs/versions retain distinct
provenance even if their byte hashes match. Projection tests preserve accepted
generation independently of current generation; guards in the current model
prevent normal advancement of an already-terminal accepted partition.

`ArtifactMetadata` contains id, attempt_id, partition_id, generation, recorded
RESERVED/VERIFIED/REJECTED status, expected_sha256/size_bytes/schema_hash, bucket,
object_key, opaque object_version, verified_sha256/size_bytes/schema_hash,
created_at, verified_at, rejection_code and
`content_verification="NOT_REQUESTED"`. These are recorded verification
metadata; passive inspection does not prove the object is currently readable.
Storage identity is text, not a fetch URL. `ArtifactSnapshot` adds job/ordinal
and the independent partition acceptance relation.

`ResultManifest` contains ordinal, authority, artifact, content_url and
verification_url. Unaccepted/orphan outputs never enter a manifest.
`ResultPage` explicitly reports parent status, completeness, total partitions
and accepted count. An artifact diagnostic failure cannot erase manifest
membership or change completion status.

## Event chronology and diagnostic payloads

`EventPage` contains job_id, direction, requested partition_id/attempt_id,
items, loaded_from_seq, loaded_through_seq, frontier_seq, has_more, next_cursor.
Frontier is `jobs.next_event_seq-1` in the same snapshot; it describes the
job's retained ending sequence, even when filters exclude events. Loaded range
is nullable for an empty page and describes only events actually delivered.
Filtered ranges may have gaps; no missing-transition/causality inference follows.

Forward defaults to `after_seq=0`, orders ascending and continues with
`after_seq=next_cursor`. Backward with no before_seq starts at the recorded tail,
selects newest matches below `before_seq` and **delivers that page in ascending
sequence order**; continue with `before_seq=next_cursor` to fetch older matches.
The backward cursor is the oldest delivered match. Supplying before_seq in
forward mode or after_seq in backward mode rejects `invalid_range`. Sequences
must be canonical ASCII decimal strings in [0, 9223372036854775807]; invalid
representations reject `invalid_cursor`. Filters must belong to the requested
job, and an attempt must belong to a supplied partition, otherwise 404.

Each `EventObservation` carries recorded job_id, seq, nullable partition_id,
attempt_id/generation, type, occurred_at, request_id, actor_type/id, from_state,
to_state and sanitized details. Identities/actors/transitions are not inferred
from surrounding events. `seq` is authoritative job-local order; occurred_at is
context. WorkerEventPage has the same range/frontier/continuation fields and
forward pagination but uses a **separate session sequence**. Worker events do
not store actors or job correlations, so those fields are not fabricated.

Details are `{state: SANITIZED|MALFORMED, values: {...}, omitted: boolean}`.
The query transfers at most 4096 UTF-8 bytes of diagnostic JSON as text, with
bounded guarded parsing (including recursion rejection). Only the fields
recorded by current producers are allowlisted by event type: artifact_id,
sequence, lease_expires_at, code, eligible_at, and worker from/to state. Values
must be bounded typed primitives: exact UUID, canonical bigint, timezone-bearing
timestamp, known server code or known lifecycle. Unknown fields are omitted;
malformed or oversized details return empty/sanitized values and an explicit
MALFORMED flag. Unknown types do not authorize arbitrary raw JSON access.
Outer diagnostic strings above 128 characters return the structured diagnostic
error; identities are never silently truncated. Raw failure detail is excluded.
JSON strings must still be rendered as escaped text by any client.

## Worker observations and definition bounds

`WorkerObservation` contains session_id, display_name, state, deployment digest,
created_at, last_seen_at, stopped_at, last_heartbeat_seq, liveness and nullable
current_attempt. Session UUID is the identity; equal display names are separate
boots. There is no host/process/CPU inventory or online/offline certainty.

Liveness is NOT_APPLICABLE for STOPPED; otherwise FRESH when
`as_of-last_seen_at < 30 seconds`, SUSPECT otherwise, preserving the existing
DB-clock rule. Clock jumps can alter that observation. It does not update
lifecycle or leases. A recorded ACTIVE assignment is returned even if deadlines
have passed; it does not mean valid live ownership, useful computation or
claim availability. Participation pages retain terminal historical assignments.
There is no durable heartbeat-series model.

`DefinitionSnapshot` returns job_id, version, parent_job_id, definition_hash,
manifest_hash, workload {name,version,digest}, typed parameters, policy,
inputs {input_ordinal,artifact_id,object_version,sha256,size_bytes,schema_hash,
row_count}, and partitions {partition_id,ordinal,slices}. Each slice has
slice_ordinal, input_ordinal, first_row, row_count. Inputs/partitions sort ordinal;
slices sort partition ordinal then slice ordinal. The complete immutable
definition is already bounded by the accepted 1 MiB canonical descriptor and
4096 inputs/partitions. Defensive probes cap materialization at 4097 inputs,
4097 partitions and 65537 slices; exceeding 4096/4096/65536 rejects a diagnostic
error, never returns a partial descriptor as complete. The 1 MiB validated
descriptor cannot encode 65536 minimum-size slice records. No input bytes are
downloaded. This route is explicit descriptor inspection, not a per-row poll.

## On-demand result verification

The verification GET accepts only a registered output UUID with an accepted
relation; unaccepted content returns `accepted_content_unavailable` (409). It
first captures the same immutable metadata/authority snapshot as artifact
inspection and closes its transaction/connection. It then calls the existing
gateway's exact-version byte reader, computes SHA-256 and byte count against
the committed values, and parses the fixed output Parquet schema. It never
reads "latest", substitutes a version, accepts a URI/key/path from a caller,
writes an incident, alters artifacts or changes accepted authority.

`VerificationSnapshot` contains the unchanged `ArtifactSnapshot` and a separate
`verification` object: state VERIFIED|FAILED, code, checked_at, object_version,
sha256, size_bytes. The latter three identify the **committed target**; they
are not claimed observed hash/size on a failed read. checked_at is the API UTC
clock when this diagnostic finishes; as_of is the earlier DB snapshot clock.
Thus storage verification is a later observation, not part of the DB snapshot.
A successful VERIFIED result means actual pinned bytes passed digest/size and
schema checks on this request. It is not semantic workload/oracle validation.

| Verification code | Meaning |
|---|---|
| verified | Actual pinned bytes passed checks |
| storage_missing | Store reports NoSuchKey/NoSuchBucket |
| version_unavailable | NoSuchVersion, absent/invalid version, or returned version differs |
| checksum_mismatch | Equal-length bytes failed the committed SHA-256 check (also covers truncated body in the existing reader) |
| size_mismatch | Reader encountered bytes beyond committed size |
| storage_unavailable | Endpoint/network SDK error or store 5xx |
| content_invalid | Parquet readability/fixed schema failure |
| transport_read_failure | Other storage client/permission/read/transport failure |

A completed diagnostic returns HTTP 200 even for FAILED verification, keeping
accepted_authority=ACCEPTED and recorded artifact status separately visible.
Failures never include transport text, credentials, endpoint responses or raw
bytes. No verification is polled automatically; clients request it explicitly.
The route may perform up to the existing 256 MiB output bound with existing
gateway transport timeouts and spooling. No background verification/cache or
durable integrity-incident history is provided.

## Capabilities and intentional gaps

Capabilities has api_revision, database_revision, authentication and a list of
{id,state,routes,reason}, using the product's **BV01-BV12** identifiers and the
frozen frontend's exact existing full IDs for BV01/BV03/BV07. Additional suffixes
only describe their existing BV category; no second taxonomy is introduced.
AVAILABLE means the route contract is shipped, **not** proof of DB/store health
or a currently reachable live cluster. Use existing health endpoints for those
separate observations. Dependency failure yields 503; it is not interpreted as
NOT_IMPLEMENTED. UNAVAILABLE is a supported capability-state vocabulary reserved
for a known unavailable implementation; R1 does not fabricate such a state.

| Product gap | R1 classification | Discovery state / decision |
|---|---|---|
| BV01 catalogue | IMPLEMENT IN R1 | AVAILABLE: paged jobs and exact summary |
| BV02 summary | DEFER | DEFERRED: no installation aggregates/KPI API; job-scoped summaries suffice for investigation |
| BV03 partition history | IMPLEMENT IN R1 | AVAILABLE: enriched page and all bounded recorded attempts |
| BV04 attempt detail | IMPLEMENT IN R1 | AVAILABLE: safe operator observation |
| BV05 artifact metadata | IMPLEMENT IN R1 | AVAILABLE: passive provenance; explicit accepted-only byte diagnostic |
| BV06 result metadata | IMPLEMENT IN R1 | AVAILABLE: accepted manifests without storage reads |
| BV07 fleet/history | IMPLEMENT IN R1 | AVAILABLE: sessions, recorded assignments, participation and lifecycle events |
| BV08 tail/filter events | IMPLEMENT IN R1 | AVAILABLE: bounded forward/backward pages and correlations |
| BV09 definition | IMPLEMENT IN R1 | AVAILABLE: complete bounded immutable descriptor |
| BV10 browser auth | DEFER | DEFERRED: reuse existing operator bearer; browser cookie/session/roles require a separate approved adapter |
| BV11 reports/controller | DEFER | DEFERRED: no report import/catalogue, shell/path proxy, fault controls or benchmark schema |
| BV12 observation clock | IMPLEMENT IN R1 | AVAILABLE: DB as_of on every operator read; explicit snapshot scope |

Unsupported by current authority model: durable heartbeats, CPU/computation
progress/timing, proven crash/online state, global event order, full verification
event trail, and durable integrity incidents. These are described honestly here;
they receive no invented BV IDs or fake endpoints. Cancellation, manual retry,
worker administration, publication controls, metrics and R2 release/benchmark
work are outside this read-only pass. The prior architecture proposal package
named by the product spec is not committed/present in this checkout; its paths
are proposals, not additional accepted runtime contracts.

## Error semantics and query behavior

The existing structured `{error:{code,message,retryable,outcome,request_id,details}}`
envelope is retained. Ordinary operator errors: 401 unauthenticated; 404 not_found
(including a correlation outside its requested scope); 422 invalid_request for
UUID/limit/status/unknown fields, invalid_cursor for bad sequence/catalogue cursor,
invalid_range for incompatible event bounds; 409 accepted_content_unavailable;
503 database_unavailable or malformed_persisted_diagnostic. Database/diagnostic
503 outcomes are not_committed: these reads cannot commit execution mutations.
Malformed details are a per-event flag, allowing the rest of the chronology to
remain inspectable. Unexpected internal errors use the existing opaque 500
handler. Verification failures use the independent result above rather than
turning a transport fault into lifecycle mutation.

Migration `0003_operator_indexes` adds only indexes: jobs(created_at,id),
jobs(status,created_at,id), attempts(worker_session_id,id), and
events(job_id,attempt_id,seq). They support stable catalogue keysets, terminal
participation beyond the existing ACTIVE-only index, and attempt-scoped event
pages. Existing partition/attempt/artifact/result constraints, PK/unique indexes
and events(job_id,partition_id,seq) cover other reads. Indexes affect write cost
but no state, guards, grants, locks or transitions. Apply the established Alembic
upgrade before serving this revision; readiness now expects this exact revision.
R1 tests migrate **disposable** databases; no retained installation migration or
deployment is claimed by the evidence pass.

Query count is constant per page, with one-to-one joins and batch loading:
partition pages execute six statements including READ ONLY/clock; partition
history five, attempt/artifact reads three, job summary/catalogue three, result
metadata four, worker catalogue/detail four, participation and worker-events
four, definition six; event pages four plus one per supplied scope filter.
Capabilities executes three. Job counts use scoped SQL subqueries rather than
row-wise HTTP/SQL calls. Definition/history enforce model bounds; every growing
catalogue/participation/event list is paged. No offset pagination, denormalized
state, cache authority, Cartesian history join or storage I/O under DB locks.
Real-service EXPLAIN tests establish index-eligible access paths with sequential
scans disabled on small fixtures; they are not production-scale latency evidence.
