# RELAY_CONTROL_BOARD_PRODUCT_SPEC_V1

Authoritative frontend product and interaction specification · V1 · 3 October 2026 (IST)

**Status:** design only. No frontend implementation, backend mutation, migration, state-machine change or deployment performed. Repository inspected: `ADITHYA-SANJEEVI/relay-contract`, commit `bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc`. GitHub HEAD was checked during this review and still resolved to this commit. This document is authoritative for the proposed UI, not an amendment to backend authority semantics.

## 1. Executive design thesis

Relay should be an execution investigation console. Its defining screen answers: **“Which attempt produced the accepted result, and what happened to the other attempts?”**

Choose a calm dark interface with a structured partition table, a selected-partition generation stack and a compact chronological evidence view. Acceptance receives the strongest visual treatment. Failed and expired attempts remain visible beneath it. VERIFIED artifacts have their own treatment and never masquerade as accepted results.

The showcase is Job Detail, not the overview. Prefer a table plus an attempt stack over a full-job DAG: Relay executes independent partitions, not arbitrary workflow dependencies. A time-scaled attempt lane is a secondary view for a selected partition where timestamps exist. A chronological stack is the default because it remains understandable when timing evidence is sparse.

Build one visual direction: charcoal surfaces, blue execution accents, teal artifact verification, green authoritative acceptance and restrained amber/red attention states. Use text and geometry as well as color. Do not add an independent Aegis product identity in V1; Failure Lab is a bounded Relay section.

## 2. What the UI must communicate

The hierarchy is job → partition → attempt/generation, with a separate accepted-result relation from the partition to one attempt-specific artifact. Generation is scoped to a partition. Worker display names do not establish identity; per-boot sessions do.

Every investigation should expose four distinct dimensions:

| Dimension | Question | Evidence |
|---|---|---|
| Recorded lifecycle | What state was committed? | Job/partition/attempt rows and durable events |
| Observed ownership | Does the recorded attempt appear within its lease/deadline at the observation time? | Lease/deadline and server observation timestamp |
| Artifact verification | Were these exact bytes verified at a recorded time? | Artifact metadata; content revalidation on explicit read |
| Result authority | Which artifact was accepted for this partition? | Accepted-result identity and acceptance event |

The browser never decides authority. A countdown reaching zero changes an observation label; it must not mutate ACTIVE to EXPIRED. Recovery produces that committed transition. Missing heartbeat means SUSPECT, not confirmed crash. Job RUNNING may contain FAILED partitions because failure policy drains remaining work. A FAILED or future CANCELLED job may retain partial accepted output; it is not a complete job result.

Do not equate deterministic matching hashes with identical provenance. Different attempt IDs, generations, object versions and acceptance relations remain meaningful even when output bytes match.

## 3. Repository-backed product capabilities

### Evidence and inspection scope

The previously materialized frozen source was inspected alongside the current HEAD verification. Sources include README, SPEC, INVARIANTS, STATE_MACHINES, DATABASE, API, FAILURE_MODEL, REFERENCE_WORKLOAD, TEST_PLAN, IMPLEMENTATION_PLAN, BENCHMARK_PLAN, M0–M3 evidence, accepted M0 amendments, API/models, SQL metadata/guards, control/publication/leases/settlement, recovery, worker/supervisor/gateway and relevant process/concurrency/publication tests.

The eight architecture proposal documents from the preceding review were available locally and consulted, especially CONTROL_BOARD_INFORMATION_ARCHITECTURE, UI_API_GAP_ANALYSIS, OBSERVABILITY_CONTRACT and DEMO_FAULT_CONTROL_BOUNDARY. They are **proposals**, not implemented endpoints or accepted backend amendments. No committed Control Board implementation or dedicated newer UI freeze was found at the checked HEAD. A hypothetical R1 implementation/evidence document is unavailable. Do not assume its changes landed.

The historical evidence records 250 test items across separate suites; this design pass did not rerun them. Source supports the recorded claim-contention and stale-generation scenarios. Those are finite correctness observations, not throughput or availability measurements.

### Implemented versus planned

| Capability | Baseline status | UI consequence |
|---|---|---|
| Job status, times, partition/attempt/accepted counts | Implemented operator read | Live Job Detail summary can use these fields |
| Paged partition state, generation, latest attempt/deadlines, accepted artifact ID | Implemented operator read | Baseline partition table available |
| Forward per-job event cursor | Implemented operator read | Chronology available; newest-tail bootstrap needs catch-up or planned backward read |
| Accepted result listing and content | Implemented; listing verifies pinned bytes | Explicit consumer access; never recurring board polling |
| Owner attempt read | Implemented worker-only authentication | Not usable by ordinary operator frontend |
| Renewal, failure, recovery, stale publication rejection | Implemented | Explain durable outcomes; reveal only available safe fields |
| Global jobs/fleet/operator attempt and artifact metadata | Stored data, missing operator reads | BACKEND VISIBILITY GAP; planned additive reads |
| Job cancellation | Documented, absent route | No enabled cancel action at baseline |
| Metrics endpoint / benchmark results | No implemented endpoint/results found | No latency/throughput/uptime cards |
| Failure test harness | Exists under tests | Evidence presentation possible; browser controller remains planned |
| Browser cookie authentication | Proposed, absent | Live browser connection requires approved auth adapter |

SPEC and planning introductions retain some “unimplemented” wording despite M3 code. Use actual routes plus milestone evidence to determine implementation status; use accepted contracts for semantics. Never reinterpret documentation drift as permission to change the engine.

## 4. Design research and relevant patterns

Primary official documentation was inspected on 2 October UTC / 3 October IST 2026. This was documentation-based interface research, not an authenticated hands-on review of paid consoles. No claim is made about unavailable screens.

| Reference | Pattern worth borrowing | Relay decision / rejected pattern |
|---|---|---|
| [Temporal Web UI](https://docs.temporal.io/web-ui) | Execution-centred navigation, compact/raw history, metadata and history export | Keep job history close to inspection. Do not copy signals, resets, task queues or workflow hierarchy |
| [AWS Step Functions execution details](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-view-execution-details.html) | Linked selection across table/detail views; retries visible in an execution timeline | Synchronize partition table, attempt stack and event focus. Do not fabricate state-machine graph edges or redrive actions |
| [Sentry Issue Details](https://docs.sentry.io/product/issues/issue-details/?promo_name=hp-banner) | Summary followed by one concrete event; visible filter scope | Keep error cause and linked attempt together. No assignment/issue-management subsystem |
| [Datadog Trace View](https://docs.datadoghq.com/tracing/trace_explorer/trace_view/) | Focused waterfall and alternate list presentations | Optional attempt timing lane backed by timestamps. No implied spans, CPU phases or full distributed tracing |
| [Grafana Logs Drilldown](https://grafana.com/docs/learning-paths/drilldown-logs/) | Guided filters and related-record drilldown | Structured failure filters. No general query console or dashboard builder |

Research inference: coordinated views help an engineer retain context while inspecting failure history. Relay’s distinct opportunity is a persistent accepted-result anchor against generation history. This is a design judgment, not a measured usability finding. Product summaries here are intentionally short; links retain source attribution.

## 5. Chosen visual direction

Use a precise, dark engineering workbench. Pages have a continuous charcoal canvas; sections use small surface steps and fine separators. The UI should feel composed at normal information density rather than cinematic.

The identity motif is the **authority rail**: a 3px green left border and a labeled diamond/check marker on accepted-result panels. Use it only for a confirmed accepted relation or a complete success summary with that meaning. Blue marks ongoing recorded execution; a numbered outlined chip identifies generation. Teal identifies VERIFIED artifact state. Old generations remain readable with subdued surfaces, never disabled opacity.

Show the word Relay in the shell with a small two-line routing glyph. No animated logo, custom mascot, glow or architectural acronym badge. The strongest branding is the consistent distinction between attempt history and accepted authority.

## 6. Information architecture

Primary navigation: **Overview, Jobs, Workers, Failure Lab, Evidence**.

- Artifacts live in job/partition context and on direct provenance routes; no global artifact browser in V1.
- Operational signals live on Overview and in the Job Activity tab; no top-level generic Observability card wall.
- Evidence contains Benchmarks and Validation manifests, which have different provenance and cannot be blended.
- Failure Lab is a scenario/evidence workspace. Running controls appear only when the separate local controller is connected and authorized.

Unsupported destinations show a concise capability explanation rather than an empty fake table. The shell supports a minimal baseline mode with “Open job by ID”; Jobs catalogue and fleet require the planned reads. In a finished R1 release those reads should be available. This frontend agent must not implement them to make a screen appear complete.

## 7. Navigation model

| Route | Purpose | Scope persistence |
|---|---|---|
| /board | Overview / open exact job ID | Environment and time display |
| /board/jobs | Job catalogue | Status, cursor, permitted server search |
| /board/jobs/:job | Showcase Job Detail | tab, partition filter, selected partition, generation, event |
| /board/jobs/:job/partitions/:partition | Permanent partition investigation | generation / event selection |
| /board/attempts/:attempt | Direct attempt deep link | Always show job/partition breadcrumb when resolved |
| /board/workers | Fleet | State/liveness/page |
| /board/workers/:session | Boot-session detail | Attempts / lifecycle tabs |
| /board/artifacts/:artifact | Exact provenance | Source job/partition and acceptance relation |
| /board/lab | Scenario catalogue | mode=recorded or live |
| /board/lab/:run | Experiment detail | step / related entity selection |
| /board/evidence | Evidence index | kind=validation or benchmark |
| /board/benchmarks/:run | Benchmark report | Metric and comparison selection |

Routes are frontend destinations, not declarations that matching backend endpoints exist. Deep links use exact UUIDs. Invalid IDs produce a local validation explanation before network requests. A 404 means not found in this installation, not deleted history. Filters/selection live in URL search parameters. Back restores the previous filter/page/scroll context. No tokens, pairing codes, raw data or filesystem paths in URLs.

A partition selected in Job Detail opens a nonmodal inspector when space permits. “Open full detail” preserves a permanent route. It must not open another modal on top of an existing drawer. Breadcrumbs use Jobs → shortened job ID → Partition ordinal → Generation, with full identities accessible by copy/reveal.

## 8. Screen inventory

| Screen | Priority | Launch dependency |
|---|---|---|
| Connection and capability state | P0 | Approved browser auth/session adapter; existing health reads |
| Job Detail and partition table | P0 | Existing job/partition/events reads |
| Partition/attempt inspector | P0 | Planned safe history/detail reads; limited event fallback |
| Jobs list / Overview aggregate | P0 finished R1 | Planned catalogue/summary |
| Artifact provenance | P0 | Planned metadata-only read |
| Worker fleet/detail | P1 | Planned safe fleet/history reads |
| Failure Lab recorded evidence | P1 | Sanitized scenario report/manifest contract |
| Failure Lab live mode | P1 gated | Separate authenticated local controller |
| Benchmark detail/comparison | R2 | Validated measurement report schema |

Connection, empty, degraded, unknown and missing-capability states are required screens, not cleanup after the happy path.

## 9. Detailed screen-by-screen specifications

### 9.1 Connection / shell

First visit: Relay title, local installation label, “Connect to this installation,” pairing input if the adapter exists, and explanatory role text. No bootstrap/operator secret input in a persistent browser form. Never save bearer secrets in localStorage. At baseline without an approved adapter, present a connection prerequisite and an explicitly labeled fixture/evidence mode; do not borrow a worker credential.

Shell: 216px sidebar, 52px utility header, breadcrumb, role, environment, last successful refresh and connection state. Header never says “All systems operational” based on one readiness response. Use separate “API reachable” and “Readiness passed/failed/unknown” observations with checked times. No tenant switcher or fake region selector.

### 9.2 Overview

Lead with “Needs attention,” an actionable list of jobs/partitions, then a compact active-work summary and fleet observation. Maximum four meaningful summary values: queued jobs, running jobs, accepted outputs in the explicitly named scope, and expired-unsettled attempts. Each value has a scope/observation tooltip and destination filter. Missing aggregates display “Unavailable,” not 0.

Attention list prioritizes terminal partition failures in still-running jobs, expired-unsettled ownership, then delayed retries. Do not infer “recovery process down” from these states. Recent failures are grouped by code and linked entity, with a displayed time window. If global endpoints are missing, replace aggregate area with Open Job by ID and capability explanation. No frontend enumeration of jobs from remembered IDs presented as installation totals.

### 9.3 Jobs catalogue

Toolbar: status filter, supported exact-ID search/open control, refresh and column preferences. Search by workload/date/prefix is only offered if the actual read contract supports it. Default descending creation order, server cursor, 100 rows. Columns: job ID, status, workload if exposed, accepted/total, READY/RUNNING/FAILED breakdown, created, elapsed, last observed. Do not invent a job display name; UUID is baseline identity.

Progress cell uses accepted/total, not terminal/total. A separate text line shows settled count if needed. A failed job can show partial acceptance without a fully green bar. No New Job wizard, global retry or bulk cancel in V1.

### 9.4 Job Detail

Defined deeply in section 10. It is the landing route for all job evidence links.

### 9.5 Partition / attempt full detail

Partition header: ordinal, full partition identity, recorded state, current generation and accepted-generation anchor. Generation stack plus selected attempt fields; current and accepted generations can differ in their interpretation and must have separate labels. Ordinal 0 is displayed as “Partition 0.” No renumbering to 1.

Attempt page reuses the inspector in a full-width context. Fields: attempt ID, generation, owning session, claim, terminal time, recorded status, failure code, lease/deadline, renewal sequence, artifact metadata and accepted linkage where safely exposed. Empty artifact means “No artifact metadata available,” not computation failure. Missing owner read means unavailable, not anonymous worker.

### 9.6 Workers

See section 13. No enabled drain, stop, restart, kill or force-reassign in normal operator mode.

### 9.7 Artifact detail

See section 15. Explicit content read is separate from passive metadata inspection.

### 9.8 Evidence

Catalogue of schema-validated reports with kind, actual source SHA, scenario/configuration identity, recorded time and PASS/FAIL/INCONCLUSIVE. Tests are not benchmarks. Reports may be imported through an approved local file/import mechanism or allowlisted report catalogue; no arbitrary server path access. Source labels say “Repository-recorded” where appropriate; do not mark historic test evidence as currently live.

## 10. Job Detail deep specification

### 10.1 Desktop composition

At 1440px viewport width: 216px sidebar; 24px main gutters; content fills the remaining width. Header contains job identity/status on the left and copy-link/export/refresh controls on the right. Beneath it, a 72–88px summary strip shows accepted/total, state breakdown, elapsed and observed time. Avoid four giant detached metric cards.

Main tabs: **Execution, Activity, Results, Definition**. Execution is the default. Within Execution, partition table occupies approximately 58–62% of available content and inspector 38–42%, with inspector minimum 360px. Allow user resizing within bounds where implementation is straightforward. Below 1280px use a full table and an accessible inspector drawer/full page. Never shrink authority content into unreadable 200px cards.

### 10.2 Header and summary

Job ID is the page title; workload/version is secondary only when exposed. Status uses actual job state. Definition hash is a labeled copy field, not an assumed semantic version. Elapsed is finished-created for terminal jobs; otherwise observed-now minus created, with approximation/freshness notation. Run duration since started is separately labeled if shown. Do not mix the two.

Acceptance progress: partial_result_count / partition_count. State strip shows READY, RUNNING, SUCCEEDED, FAILED and CANCELLED counts returned by the summary. Counts have accessible text equivalents. Retry count from the existing aggregate can be derived as attempt_count minus partitions ever claimed only if those claimed partitions have actually been counted; otherwise show unavailable or use planned authoritative aggregation. Never use attempt_count minus total partitions when some remain generation 0.

Terminal FAILED header: “Job failed · partial accepted results retained” when accepted count is positive. Active job with failures: “Work continues; failed partitions will make final outcome FAILED.” Cancellation wording is gated on a future implemented contract.

### 10.3 Partition table

Default page 100; status filter supported today. Ordinal ascending. Columns in priority order: partition, recorded state, current generation, accepted artifact/authority, latest attempt, lease observation, retry eligibility, last error. Expanded owner/artifact fields require planned reads.

Click row or explicit Inspect opens selection; row itself is not the only keyboard target. Keep ordinal/state/generation/acceptance pinned conceptually when horizontal scrolling is required. The accepted cell links to exact artifact; absence says “None accepted.” A SUCCEEDED row missing its expected linkage is an inconsistent observation to refresh/investigate, never filled with a guessed artifact.

Filters “Retried,” “Deadline passed,” and “Accepted generation” require supported server filters or page-scoped filtering labeled “This page.” Do not claim a global match count from one page. Clear filters restores the cursor to the start. Selection retains entity identity through refresh even if its row moves out of the current page.

### 10.4 Inspector structure

1. Partition title and recorded state.
2. Persistent accepted-result panel: “Accepted generation G” with attempt/artifact/version links, or “No accepted result.”
3. Current-observation line: current generation and ownership/deadline observation.
4. Generation stack, newest generation first; each card has G-number, lifecycle, owner if known, artifact state and publication outcome.
5. Selected-generation detail and correlated event slice.
6. Links to full partition/attempt/provenance pages.

Keep accepted panel visible while scrolling inspector. Acceptance is not a badge inferred from a generation’s green-looking workload status; resolve its identity from the accepted relation. When the baseline exposes only accepted_artifact_id, say “Accepted artifact” and withhold accepted generation until lineage can be resolved from safe metadata or a linked RESULT_ACCEPTED event. Do not assume the latest generation alone proves it.

### 10.5 Activity tab

Bounded ordered event list; select partition/attempt when the contract supports server filtering. Baseline fallback filters only events already loaded and explicitly states that limitation. Collapse consecutive renewal events as “N renewal events in this loaded range,” retaining expand/raw access. Never call renewal sequence a total event count.

Show sequence number as primary ordering key, UTC/local timestamp as context, human summary and raw event type. Clicking a linked event selects its partition/generation without losing job context. Unlinked events remain job-level; do not fabricate IDs from nearby events. An event boundary label distinguishes the loaded range from full retained history.

### 10.6 Results tab

Metadata-only manifest is planned and preferred. Baseline consumer results endpoint can be called by an explicit “Load verified accepted manifests” action with an integrity-work notice; never auto-poll it. Show incomplete/partial banner unless complete=true and job SUCCEEDED. Download reads remain explicit.

A content integrity failure does not remove acceptance. Keep authority visible and add “Pinned content could not be verified on this read,” time/request ID and retry action. No “repair,” substitute version or rerun button.

### 10.7 Definition tab and actions

Immutable workload/policy/input manifest needs planned safe definition read. Definition hash is available now. Render structured fields first, escaped JSON second. Do not allow editing an existing definition.

Export event trace includes job/source identity, retrieval time, loaded/full scope and actual events; no secrets. Full export fetches pages explicitly under a size budget, deduplicates by job+seq, reports captured ending sequence and does not claim an atomic system-wide snapshot.

Cancel is absent at baseline. Hide it from live action menus or show a clearly disabled explanatory item. After the separate backend pass implements/tests it, operator-role cancellation uses confirmation with immutable accepted-result retention wording, bounded reason, pending/unknown states and authoritative reread. No optimistic CANCELLED, no assumed child termination. No rerun/resume/retry/force-accept control.

## 11. Partition / attempt / generation visualization

### Chosen model

Use an **attempt stack with an authority anchor**, coordinated with a compact timeline. Do not draw a DAG for the full job. A partition’s generations are successive ownership episodes, not arbitrary compute dependencies.

A generation card has three independently labeled rows:

- Attempt lifecycle: ACTIVE / EXPIRED / FAILED / SUCCEEDED / CANCELLED.
- Artifact: unavailable / RESERVED / VERIFIED / REJECTED.
- Publication: accepted / known rejection code / no acceptance observed.

“Computation completed” is not a durable baseline lifecycle state. Only show it as a harness-recorded observation with that source. VERIFIED demonstrates recorded byte/schema verification; it does not grant publication authority or establish an arbitrary mathematical correctness claim.

### Synthetic layout example — not production data

| Partition 17 generation | Recorded attempt | Artifact | Publication evidence |
|---|---|---|---|
| G5 | SUCCEEDED | VERIFIED · artifact B | ACCEPTED · authoritative relation |
| G4 | EXPIRED | VERIFIED · artifact A | REJECTED · stale_generation |
| G1–G3 | EXPIRED | Not shown in this illustration | No acceptance shown |

This table illustrates layout only. Runtime IDs, timestamps and counts must come from actual reads or an explicitly labeled evidence fixture. Old G4 remains EXPIRED after late rejection; never rewrite its status to STALE or FAILED. STALE is a relative/operation observation badge, not a stored attempt enum. Artifact A remains VERIFIED, not REJECTED, because publication rejection and artifact validation rejection differ.

### Time-scaled lane mode

Opt-in selected-partition view: one row per generation, common time axis, claim-to-terminal segment for terminal attempts; ACTIVE segment ends at as_of and uses an open end marker. Label this span “Recorded ownership episode,” not CPU execution duration. Lease expiry and hard deadline have distinct markers; extension history appears only with actual renewal events. Do not reconstruct an earlier lease timeline from the final lease value.

Acceptance marker is a green diamond tied to accepted_at; publication rejection is a red outlined marker tied to event seq/time. Verified_at uses a teal outlined annotation labeled “Metadata observation — no event sequence.” Multiple same-time events retain sequence order in their accompanying list; never infer causality solely from timestamps. Dashed gaps represent backoff only where eligible_at or transition details establish it. Unknown intervals stay unfilled and labeled unknown.

Use a small lineage strip in artifact detail only: partition → accepted relation → exact artifact, with attempt/generation as linked provenance. No topology graph of every worker/job/object.

## 12. Failure Lab specification

Failure Lab presents reproducible experiments, not a toy bank of red buttons. Header always labels **RECORDED EVIDENCE**, **RECORDED REPLAY**, or **LIVE LOCAL EXPERIMENT**. Never mix modes inside an apparently live fleet.

### Scenario availability

| Scenario | Actual basis | V1 presentation |
|---|---|---|
| Generation 4 stale completion after generation 5 acceptance | M3 process test / evidence | Primary recorded scenario; live controller planned |
| Worker interruption and reassignment | Existing fault tests | Recorded evidence; optional later controller scenario |
| Claim contention | Existing 32-session race | Evidence only; not “32 compute workers” |
| Publication contention | Existing publication tests | Evidence-only winner/rejection inspection |
| Response loss after acceptance | Existing reconciliation tests | Recorded transport boundary; not proof of connection loss at COMMIT |
| Cancellation after verification | Existing proposal, absent implementation | Planned/unavailable until backend gate passes |

### Experiment page

Top: scenario title, invariant, mode, actual repository SHA, evidence reference and run status. Next: expected behavior and observed verdict side by side. “Not evaluated,” “Inconclusive,” “Failed” and “Passed” are distinct.

Middle: action ledger and durable-event ledger with source chips. Harness actions are not database events. Selected step highlights the correlated partition/attempt in the reused inspector. Bottom: final accepted-result identity, retained artifacts, checks performed and sanitized evidence download/source links.

Recorded replay controls: play/pause, previous/next meaningful step, speed and jump to acceptance/rejection. No fabricated interpolation between captured snapshots. Replay time is captured scenario time; current wall-clock countdowns are disabled.

Live controller controls: fixed scenario selection, start, one permitted next action, export and reset. Capability comes from the controller’s explicit run/phase response. Browser never submits a PID, shell command, SQL, arbitrary path or object key. Pending action disables duplicate submissions; lost response produces “Action outcome unknown — reconciling,” not presumed success. Controller disconnect freezes action controls, retains observations and labels the run interrupted/unknown until reconciled.

Authority must come from runtime reads. A controller step named “B accepted” cannot paint the accepted rail until a runtime relation or captured authoritative snapshot supports it. Reset starts a new isolated allocation/identities after export; it does not delete or roll back ordinary runtime history.

The baseline generation-1–3 setup and eligibility acceleration are fixture-assisted. The evidence page states this. The future live segment should wait genuine generation-4 expiry/backoff per the prior contract; frontend code cannot accelerate time or advance generation.

## 13. Worker experience

Fleet table columns: shortened session ID, display name, lifecycle state, heartbeat observation, last contact, current recorded ACTIVE attempt, workload digest. Session ID is primary. Identical names remain separate boots. Historical STOPPED sessions are paged separately from current registered/draining sessions.

Lifecycle and liveness use separate badges. FRESH/SUSPECT are server observations under the documented 30-second rule; STOPPED uses “Liveness not applicable.” A current expired-but-unsettled attempt still occupies the recorded session; do not label its worker available based on a countdown.

Session detail has Identity, Participation and Lifecycle tabs. Show latest contact, compatibility digest and safe attempt links. There is no heartbeat history graph at baseline. No CPU utilization, pod/host/node map or “healthy capacity” estimate. Claim scheduling eligibility cannot be inferred from REGISTERED+FRESH alone.

BACKEND VISIBILITY GAP: fleet and participation operator reads do not exist. Existing worker-self heartbeat/drain/stop endpoints must not be called using browser-held worker secrets. Keep this section read-only even after the read gap closes.

## 14. Observability experience

Operational signals are placed next to the affected workflow, with explicit scope. Overview shows current eligible/delayed queue, expired-unsettled state and latest dependency observations only when exposed. Job Activity shows retry schedules versus retry claims, failure codes and stale publication rejections.

Counts of known committed PUBLICATION_REJECTED events describe durable publication attempts, not every transport failure. Exact replay must not inflate durable counts. A retry scheduled but not yet claimed is different from an extra computation. Duplicate computation is demonstrated by attempt/harness evidence, not accepted count minus artifact count.

No persistent operational history exists for many measurements. Session-local polling history, if later introduced, is labeled “Observed in this browser since [time]” and has discontinuities for missed polls. Prefer no such chart in R1. Missing data is a gap, never a connecting interpolated curve.

R2 Benchmarks has only three chart groups: useful throughput/scaling; fault/recovery distribution; extra-work bounds. Every chart includes sample count, units, failures/censoring and configuration identity, plus a table alternative. Reject comparison when workload/layout/timing/machine/configuration differs materially; allow side-by-side inspection labeled incomparable. Measured values require actual validated reports. No placeholder KPI can appear in a live view.

## 15. Result / artifact lineage experience

Artifact detail begins with two independent labels: **Artifact verification state** and **Acceptance relation**. Both remain visible while inspecting storage identity.

Field groups:

1. Authority: accepted partition, attempt, generation, accepted_at, completeness of parent job.
2. Origin: job/partition/attempt/generation, reservation/verified time.
3. Exact bytes: bucket, full key, opaque object version, SHA-256, byte size, schema hash.
4. Read observation: last explicit read result in this session, request ID/time; unknown until checked.

Copy controls retain exact full strings, including opaque version encoding. Short IDs/hashes show first and last segments with full reveal; never truncate by losing copyable bytes. URI is text, not an external arbitrary fetch link. No store-console/write-credential link.

VERIFIED with no accepted relation is “Verified · unaccepted.” If publication still appears possible, use “Awaiting publication/acceptance observation.” If old/terminal, explain retained unaccepted output. The word orphan may appear in the technical details tooltip, not as a deletion recommendation. No garbage-collection UI.

Explicit “Read accepted content” or “Download accepted output” is available only for permitted accepted content. An ordinary operator cannot inspect arbitrary unaccepted bytes through a worker credential. A missing/corrupt exact version leaves the green authority relation intact with a separate integrity-read warning. Never choose the newest object version as fallback.

## 16. State and status taxonomy

| Object / meaning | Text and visual | Forbidden interpretation |
|---|---|---|
| Job QUEUED | Queued · neutral clock | All partitions have never run |
| Job RUNNING | Running · blue activity icon | No partition has failed |
| Job SUCCEEDED | Succeeded · green check | General SLA/uptime proof |
| Job FAILED | Failed · red stop icon | No accepted partial output |
| Job CANCELLED | Cancelled · neutral stop; future implemented gate | All OS processes instantly stopped |
| Partition READY | Ready · neutral; delayed retry shown amber separately | Immediate claim guarantee |
| Partition RUNNING | Running · blue | Child is definitely computing now |
| Partition SUCCEEDED | Accepted result · green, stored state in detail | Arbitrary workload mathematically correct |
| Attempt ACTIVE | Active · blue; separate deadline observation | Unconditionally authorized right now |
| Attempt EXPIRED | Expired · amber clock | Same as crash diagnosis |
| Attempt FAILED | Failed · red with safe failure code | Artifact must have been rejected |
| Attempt SUCCEEDED | Accepted attempt · green | Separate computation-success enum |
| Artifact RESERVED | Reserved · neutral outline | Bytes already uploaded |
| Artifact VERIFIED | Verified · teal outlined check | Accepted or currently readable forever |
| Artifact REJECTED | Verification rejected · red | Stale publication rejection |
| Publication stale_generation | Publication rejected · red outline; Stale badge neutral/amber | New terminal attempt state |
| Worker REGISTERED/DRAINING/STOPPED | Neutral / amber / neutral lifecycle chips | Cluster health or CPU capacity |
| Worker FRESH/SUSPECT | Blue / amber observation chips | Ownership renewal or proven crash |
| Deadline passed, ACTIVE retained | Deadline passed · awaiting settlement | Committed EXPIRED |
| Unknown / stale data | Neutral question / amber freshness strip | Zero, healthy or terminal |

Recorded enum, derived observation and harness-only phase have different chip captions/tooltips. Pair color with words and symbols. Use green for acceptance/success, not every successful HTTP response. Never flash the whole row when a renewal arrives.

## 17. Design system

### Color tokens

| Token | Hex | Role |
|---|---|---|
| canvas | #0B1017 | Page backdrop |
| surface-1 | #111923 | Tables, panels |
| surface-2 | #172230 | Selected panels / raised regions |
| surface-hover | #1C2B3B | Hover background |
| border-subtle | #2A394B | Decorative section dividers |
| border-control | #62758D | Required form/control boundaries |
| text-primary | #E7EDF5 | Main text |
| text-secondary | #ADBCCD | Supporting text |
| text-muted | #8B9EB4 | Timestamps / unavailable explanations |
| execution | #86B7FF | Recorded activity / links |
| accepted | #79D9AA | Confirmed acceptance |
| verified | #6DD3D0 | Artifact verification |
| attention | #F0C674 | Delay / suspect / degraded |
| failure | #FF929B | Failure / publication rejection |
| focus | #BDD5FF | Keyboard focus ring |

Colored text is used on dark surfaces, with subtle tinted backgrounds and text/icon labels. Solid primary button uses execution background and canvas-colored text. Do not use white text on every bright semantic fill. Subtle dividers are not sufficient to identify an interactive control; use border-control/focus where needed. Contrast checks must be repeated on actual composed states; hex tokens alone do not certify accessibility.

### Typography, spacing and density

Use locally bundled Inter Variable for interface text, with system sans fallback; JetBrains Mono for IDs, values and code, system monospace fallback. Record font license and avoid runtime third-party font requests. Main title 24/32px weight 600; section title 16/24px 600; body/table 14/20px 400; labels 12/16px 500; mono 12–13/18px. Minimum informational text 12px. Tabular numerals for counts/times.

Spacing scale: 4, 8, 12, 16, 24, 32px. Panel padding 16px; major gutters 24px; table row 44px default, 36px optional compact mode; header row 40px. Buttons minimum 32px height; dense icon controls at least 28×28px, with adequate separation. Touch fallback uses 44px targets. Radius 6px controls, 8px panels; status pills radius 4px rather than inflated capsules.

No panel shadows in normal page layout. Dialog/drawer elevation is a restrained dark shadow plus clear border. Icons: consistent 16px outline set, 1.5–2px stroke; no mixture of emoji and production icons. Motion ≤150ms opacity/color/position transitions; reduced-motion disables movement and pulse. No animated throughput counters, permanent spinning status icons or success confetti.

## 18. Component inventory

| Component | Responsibility / contract |
|---|---|
| AppShell / ConnectionStrip | Environment, role, freshness, navigation |
| ObjectIdentity / CopyField | Exact ID/value reveal and copy without secret leakage |
| RecordedStatusBadge | Object-specific enum; no inferred authority |
| ObservationBadge | Source/as_of, derived liveness/deadline |
| AuthorityPanel | Confirmed accepted relation or explicit absence/unknown |
| JobSummaryStrip | Scoped counts and acceptance progress |
| PartitionTable / FilterBar / CursorPager | Bounded server pages and page-scope honesty |
| GenerationStack / GenerationCard | Independent lifecycle/artifact/publication dimensions |
| AttemptInspector | Safe detail DTO, unavailable fields explicit |
| EventList / RenewalGroup / EventDetails | Ordered durable chronology with raw escaped detail |
| AttemptLane | Optional timestamp-backed ownership span |
| ArtifactProvenancePanel | Exact metadata and acceptance relation |
| WorkerSessionTable | Lifecycle separate from liveness |
| CapabilityGap / DataState | Missing capability, empty/error/stale/degraded distinctions |
| ExperimentHeader / ActionLedger / InvariantVerdict | Evidence provenance and separate harness/runtime sources |
| BenchmarkChart / AccessibleDataTable | Validated report only, counts/units/censoring |
| ConfirmActionDialog | Only supported actions; pending/unknown reconciliation |

Every data-bearing component accepts explicit loading/error/as_of/source/capability state. Do not hide unsupported values in optional chaining that silently renders a dash indistinguishable from null.

## 19. Table patterns

Use semantic HTML tables for ordinary pages. Sticky header within a bounded scroll area; avoid several nested horizontal scrollers. Sorting is offered only for supported server sort fields; page-only sort says “Sort this page.” Numeric fields align right with tabular digits. IDs align left in monospace. Tooltips supplement visible labels, never replace them.

Rows use 1px separators, subtle hover and a selected left indicator. Selection is not acceptance: blue selection outline cannot replace green authority rail. No zebra striping if it competes with semantic status. Multi-select/bulk actions are excluded.

Cursor controls say Previous / Next and Loaded N, not Page X of Y without an exact total. Previous uses retained cursor history or rereads, never an invented offset. Changing filters resets pagination. No infinite scroll fetching all partitions silently. Optional virtualization only for measured rendering need; preserve accessible row navigation and nonvirtualized bounded alternative.

Copy click does not also select/navigate the row. Safe labels use textContent/escaped rendering. Visible column preferences may persist locally; sensitive data, authorization and identities are not stored unnecessarily.

## 20. Timeline / visualization patterns

Chronology uses `(job_id, seq)` identity and ascending sequence by default. Worker lifecycle uses its own session sequence; there is no global order across jobs/sessions. Display timestamp ties without sorting against their logical sequence.

Default page is newest bounded events only when backward-tail read exists. Baseline forward API starts at seq 0 and catches up explicitly with a loading progress message; never silently claim it has reached the tail. With planned reads, load latest 100 and “Load earlier,” then follow forward. Keep ≤1000 recent events in the view before requiring explicit earlier-history reload. Exports are separate from visible memory.

Follow-tail is opt-in/visible; it pauses when the user reads older events. New event count appears in a small “N new events” control. Do not autoscroll while inspecting an event. Group only adjacent matching renewals in the loaded range; expanding preserves every seq.

Authority edges require explicit identity links. ARTIFACT_RESERVED is durable; ARTIFACT_VERIFIED is not a baseline event. Verified_at annotation has no synthetic seq. Heartbeats have no baseline durable historical trail. Unknown transport outcomes have no invented publication rejection event.

Charts show data gaps, actual units, sample sizes and source. No smoothed recovery curves over five observations, no average of p95 values labeled pooled p95, and no ideal scaling line labeled measured performance. Each lane/chart has an equivalent ordered text/table interpretation.

## 21. Empty / loading / error / degraded states

| Condition | Presentation | Action |
|---|---|---|
| First fetch loading | Stable shell, labeled skeleton rows; no placeholder values | Cancel obsolete request on route change |
| Zero jobs from supported catalogue | “No jobs in this scope” | Clear filter / open known job |
| No accepted result | Explicit neutral authority panel | Inspect attempts; do not promise eventual success |
| Missing capability | “Not exposed by this backend” + needed read contract | No repeated failing poll or fake data |
| Background fetch | Keep last data, subtle refreshing label | Avoid table reflow |
| Network loss | Last observation time, disconnected strip | Backoff / retry / reconnect catch-up |
| 401 | Session ended; pause protected queries | Reconnect without erasing investigation URL |
| 403 | Role/operation unavailable | No worker-credential workaround |
| 404 | Entity not found in this installation | Check exact ID/environment |
| 422 | Invalid request or explicit integrity failure, distinguished by code | Show safe explanation/request ID |
| 503 outcome unknown | Unknown operation result or unavailable read | Reconcile; never infer rollback/success |
| One dependency degraded | Show observed API/readiness/read errors separately | Keep accessible metadata panels working |
| Malformed report/unknown schema | Reject report rendering | Show validation errors; no guessed values |
| Inconsistent related snapshots | “Refreshing related state” and as_of labels | Refetch bounded reads; never merge into invented fact |

Cross-endpoint snapshots may differ; mark observation times. If contradiction persists, show inconsistent observation, not a frontend repair. Failure text is safe allowlisted explanation plus raw code. Raw backend failure_detail is not an operator DTO and must not be exposed.

## 22. Responsive behavior

Target screenshot sizes: 1440×900, 1366×768, 1280×800, 1024×768 and 768×1024. 1440p displays may use larger vertical resolution; avoid fixed-height assumptions.

- ≥1280px: full sidebar; table/inspector split where minimum widths fit.
- 1024–1279px: sidebar collapsed to a labeled accessible rail/navigation overlay; inspector opens drawer or full page; prioritize authority/state/ordinal.
- 768–1023px: stacked summary, bounded horizontally scrollable table, full-page partition inspector. Failure Lab remains evidence-readable; destructive/live controls need enough space and explicit confirmation.
- <768px: readable identity/status/authority/history and explicit “Best inspected on desktop.” No promise of live-lab control parity. Do not turn all 4096 rows into cards.

At 200% zoom allow responsive stacking. Header controls wrap without covering status or authority. Sticky elements must not obscure keyboard focus. Hashes/versions can wrap in detail, while exact copy retains original string.

## 23. Accessibility considerations

Aim for WCAG 2.2 AA and verify against the [W3C quick reference](https://www.w3.org/WAI/WCAG22/quickref/). Normal text ≥4.5:1; large text and essential graphical/control boundaries ≥3:1. State distinctions have words/icons and never rely solely on hue.

Use landmarks, skip link, visible focus, real buttons/links, heading hierarchy, table headers and accessible tab semantics. Nonmodal inspector is a labeled region; modal drawer/dialog traps focus, supports Escape and returns focus to trigger. Generation selection and event expansion work without pointer hover. Icon buttons have explicit accessible names.

Live refresh announces only important changes through a polite throttled status region. Do not announce a countdown every second, every renewal or every cell update. Acceptance/rejection changes may announce once with selected entity context. Screen readers get clear “Recorded status,” “Observation” and “Accepted result” labels.

Support reduced motion, keyboard-only complete investigation and copy feedback. Provide chart/lane text equivalents and accessible data tables. Confirm live-lab action consequences with text; do not require dragging/panning to access evidence.

## 24. Existing backend-data mapping

Base paths below are real baseline routes. Use approved same-origin auth adapter, not raw secrets in browser code. DTO definitions must be taken from actual API responses; bigint decimal strings are not coerced into unsafe JS Numbers.

| Route | Auth / fields used | Frontend use and limitations |
|---|---|---|
| GET /health/live | Unprotected liveness | API process observation, not dependency health |
| GET /health/ready | Existing readiness | DB revision/store readiness observation; no historical uptime |
| GET /v1/jobs/{id} | Operator; id, definition_hash, status, timestamps, partition_count, attempt_count, partition_counts, next_event_seq, partial_result_count, complete | Job summary; no workload/definition/fleet fields |
| GET /v1/jobs/{id}/partitions | Operator; after_ordinal, limit 1–500, status; id/ordinal/state/generation/eligible_at/last_error_code/latest attempt and deadlines/accepted_artifact_id | Page and limited current inspection; no complete attempt history/owner metadata |
| GET /v1/jobs/{id}/events | Operator; after_seq decimal string, limit 1–500; seq/type/time/linkage/details | Durable chronology; forward only, no global or backward cursor/filter promise |
| GET /v1/jobs/{id}/results | Operator; ordinal page, accepted metadata and complete | Explicit verified manifests only; verifies exact objects on every page |
| GET /v1/artifacts/{id}/content | Operator accepted-only or owning worker | Explicit accepted content download; integrity failure does not revoke acceptance |
| GET /v1/attempts/{id} | Owning worker | Do not use for ordinary board; requires new safe operator read |
| Worker heartbeat/drain/stop | Worker-self | Not operator fleet APIs; remain outside normal board |
| POST complete/fail/renew/artifact operations | Worker-owner protocol | Never exposed as normal frontend controls |
| POST /v1/jobs and input operations | Existing operator mutations | Outside this inspection-focused UI V1; no job-creation wizard |

Existing pagination next_cursor=null means end of that snapshot page range, not a durable event subscription cursor. Retain highest received event seq across polling. Do not use next_event_seq-1 to skip events not retrieved. Fields returned in separate calls are separate observations; current baseline responses do not expose the full proposed as_of contract.

## 25. Backend visibility gaps

These are requirements for a separate backend agent. **Do not implement them in this UI session or substitute direct database access.** Proposed paths below reference the prior read-model proposal and remain unimplemented.

| Gap | Required safe visibility | Proposed contract / UI benefit |
|---|---|---|
| BV01 catalogue | Paged jobs with supported filter/order and workload | /v1/operator/jobs; navigation without enumerating known IDs |
| BV02 summary | Scoped SQL gauges, query window, DB as_of | /v1/operator/summary; honest overview |
| BV03 partition history | ≤10 attempts, owners, artifact state, accepted generation | /v1/operator/partitions/{id}; accurate generation stack |
| BV04 attempt detail | Safe operator DTO, lease/deadline/renew sequence/failure code | /v1/operator/attempts/{id}; no worker secret |
| BV05 artifact metadata | Exact version/hash/schema/size, verification and acceptance relation | /v1/operator/artifacts/{id}; passive provenance with zero store reads |
| BV06 result metadata | Acceptance relation without object verification | /v1/operator/jobs/{id}/result-metadata; safe polling |
| BV07 fleet/history | Safe sessions, current attempt, lifecycle and paged participation | /v1/operator/workers plus scoped history; fleet read-only |
| BV08 tail/filter events | Backward/latest page and partition/attempt filters | Planned operator event read; bounded meaningful chronology |
| BV09 definition | Stored immutable policy/workload/input slices | Planned definition read; no storage download needed |
| BV10 browser auth | Scoped viewer/operator cookie, CSRF, Origin checks | Prior auth adapter; live connection prerequisite |
| BV11 reports/controller | Validated evidence/report catalogue; isolated controller run/action state | Prior benchmark/demo contracts; no shell/path proxy |
| BV12 observation clock | DB as_of and snapshot scope on reads | Reliable countdowns/freshness; countdown remains nonauthoritative |

Further state gaps intentionally not requested: durable heartbeats, live CPU/progress, full verification event trail, global event sequence and integrity incident persistence. No new state should be created merely to fill a visual card.

Cancellation remains absent and has a previously identified consistency-guard conflict for READY retries with terminal latest attempts. This document does not resolve it. A backend agent must reproduce, amend narrowly and test before the action is enabled. Workload-oracle overflow mismatch likewise gates broad correctness labels; frontend must never paint all workload results “Oracle validated” from an artifact hash.

## 26. Explicit non-goals

No backend implementation; no publication-fence, lock-order, lease-clock, generation, recovery or immutable-history changes. No optimistic authority/state writes. No direct DB/object-store credentials, worker impersonation, arbitrary URLs or raw unsafe failure details.

No workflow DAG builder, autoscaler, Kubernetes console, remote worker management, tenant/RBAC product, alerts/SLA system, global tracing platform, SQL/query editor, mutable job editor, result repair/GC, force acceptance, arbitrary fault hooks, or a dashboard builder. No WebSockets/SSE in V1. No unsupported uptime/throughput numbers. No parallel Aegis branding/product scope.

## 27. Frontend implementation architecture recommendation

Use React + TypeScript + Vite, React Router, TanStack Query, TanStack Table, an accessible primitive component library and a consistent outline icon set. Use CSS variables for tokens; utility CSS is acceptable if it consumes these variables consistently. Recharts for validated R2 report charts; optional TanStack Virtual only after measured rendering need. No Next.js SSR requirement for this authenticated local console.

Organize by domains: connection, jobs, partitions, attempts, workers, artifacts, experiments, evidence; shared UI tokens/primitives; typed API adapters; typed report validators. Separate existing-route adapter, planned-operator adapter and explicitly labeled fixture/report adapter. Capability configuration is explicit, not guessed by repeatedly calling nonexistent routes. Unknown report schema rejects rendering. Validate enum/identity/string counters; preserve unknown future enum as unsupported state, not success.

One shared query cache per tab; stable keys include environment and scope/filters. Poll job/visible partition at 2s, selected detail at 1s only when supported, fleet/overview at 5s, open terminal timeline at 10s. Pause hidden tabs, refetch on focus/reconnect, cancel obsolete requests, prevent overlap and use jittered capped retry backoff. Do not auto-retry unsafe mutations with a new identity. Keep immutable definition/identity fragments separate from refreshing authority relations.

A two-second auth-scoped backend summary cache is a proposal, not frontend authority. The board must function without it. Avoid N+1 attempt/artifact reads per table row; enriched page DTOs should close those gaps. Do not poll every expanded generation independently. Bound recent events at 1000 and ordinary pages at 100. Sensitive live responses use private/no-store; browser memory is not durable truth.

Approved release direction is serving compiled assets under /board from FastAPI with scoped auth adapter. During development, use same-origin proxy with exact allowed origins. This agent can configure frontend proxy against existing approved endpoints; it must not add backend auth handlers itself. If unavailable, deliver a clearly labeled fixture/evidence UI and list live integration blockers. Fixture adapters are opt-in and have a persistent synthetic-data banner; never silently fallback to fixtures after a network error.

## 28. Suggested implementation phases

These are frontend build slices within the existing two finishing passes, not new backend milestones.

1. **Foundation and honest data adapters:** tokens, shell, connection/capability states, status taxonomy, exact identities, fixtures explicitly labeled. Verify real route shapes and auth dependency before live requests.
2. **Showcase first:** Job Detail summary/table, partition selection, generation stack, authority panel and event list. Complete keyboard and degraded-state behavior before dashboard polish.
3. **Complete R1 inspection:** catalogue/overview, safe attempt/artifact/worker integration when approved reads exist, deep links, exports and recorded Failure Lab. Live Lab only after separate controller/security gates. Cancellation only after its independent implementation gate.
4. **R2 measured evidence:** validated benchmark reports, three chart groups, comparable-run checks, evidence references and reproducible visual QA.

If a dependency is missing, mark it in the implementation handoff and keep the dependent control unavailable. Do not expand engine scope to unblock the frontend. Preserve the frozen backend regression baseline; frontend tests exercise adapters/interaction/data honesty, not duplicate its distributed-state-machine tests.

## 29. Acceptance checklist for the frontend implementation agent

### Semantics and data

- [ ] VERIFIED, attempt lifecycle and accepted authority are distinct in every view.
- [ ] Old EXPIRED attempt remains EXPIRED after stale publication rejection; artifact remains VERIFIED where appropriate.
- [ ] Accepted identity is resolved from explicit linkage, never highest generation/color/hash alone.
- [ ] RUNNING job with FAILED partitions and terminal job with partial accepted output render correctly.
- [ ] Expired-but-unsettled ACTIVE is distinguished from committed EXPIRED.
- [ ] Worker lifecycle/liveness/ownership are independent; SUSPECT is not “crashed.”
- [ ] Unknown/missing capability/null/empty/zero have distinct meanings.
- [ ] No throughput/uptime/progress/CPU/oracle figures are invented.
- [ ] Existing results endpoint is explicit-only; passive board reads have no hidden store verification.
- [ ] Sequence cursor survives next_cursor=null; late terminal rejection appears after refresh/reconnect.
- [ ] No scope-wide filter/count is inferred from a page.

### Interaction and security

- [ ] Job → partition → generation → artifact investigation works by keyboard and permanent URL.
- [ ] Back navigation preserves context; refreshing a deep link resolves safely.
- [ ] No secrets or unsafe failure payloads appear in browser storage, URLs, DOM or exports.
- [ ] Normal fleet is read-only; owner mutation endpoints cannot be invoked from board.
- [ ] Baseline cancellation has no enabled action; gated future action never optimistic-writes state.
- [ ] Recorded replay/live/synthetic modes remain visibly distinct.
- [ ] Lab controls cannot select arbitrary resources or bypass controller phase authorization.
- [ ] Integrity failure preserves accepted relation and does not substitute object version.

### Visual / accessibility / performance

- [ ] Screenshot matrix passes at declared sizes; no clipped authority/deadline/failure text.
- [ ] 200% zoom, keyboard focus and reduced motion work; color is not sole state signal.
- [ ] Actual text/control contrast passes on every state surface.
- [ ] Tables remain bounded and responsive; no 4096-row recurring fetch/render.
- [ ] One interval owner per resource; no hidden-tab polling or row-wise N+1 storm.
- [ ] Refresh retains selected entity and inspection scroll; timeline does not force autoscroll.
- [ ] Benchmark charts have units/sample counts/raw tables and reject invalid reports.
- [ ] Fixtures cover loading, disconnected, 401/403/404/422/503, malformed data, missing capabilities and partial results.

## FRONTEND_IMPLEMENTATION_HANDOFF

**Build:** Relay’s inspection console following this specification. Primary deliverable is Job Detail with a partition table, accepted-result anchor, generation stack and ordered evidence. Use the one prescribed dark visual system; do not invent additional branding or backend features.

**Page order:** connection/shell → Job Detail → partition/attempt detail → provenance → jobs/overview → workers → recorded Failure Lab → live Lab after controller gate → measured benchmarks in R2.

**Component order:** tokens and accessible primitives → status/observation/copy fields → AuthorityPanel → summary/table/cursor controls → GenerationStack/AttemptInspector → EventList → provenance/fleet → evidence/lab → benchmark charts.

**Existing contracts:** actual job, partition and forward-event operator reads; explicit accepted manifest/content reads; liveness/readiness observations. Use planned /v1/operator reads only when another agent has implemented and documented them. Worker-owner routes are not operator reads. Baseline lacks catalogue/fleet/history/metadata/browser-auth/cancel/metrics/controller; mark BACKEND VISIBILITY GAP rather than inventing support.

**Read-only:** jobs/definitions/partitions/attempts/workers/artifact metadata; ordinary frontend never claims, renews, fails, completes, reserves output, drains/stops a worker or changes acceptance. Future cancellation and local-controller actions require separately approved implemented contracts and reconciliation.

**Never modify:** PostgreSQL authority, publication predicate/rowcount gate, lock order, post-lock clock sampling, generation increments, immutable deadlines/acceptance/history, pinned object identities, recovery/retry semantics, worker credentials, existing backend source/migrations. This is a frontend build, not another engine pass.

**Visual invariants:** green authority rail only with acceptance evidence; VERIFIED teal; ongoing blue; delays/suspect amber; rejection/failure red; neutral cancelled/stopped/history. Color always has text/icon. Old generations remain legible. No decorative live graphs or fake KPI cards.

**UX invariants:** exact copy/deep links, context-preserving selection/back navigation, bounded pages/history, scope/as_of/source labels, unknown distinct from zero, no optimistic authority, metadata failure separate from content-read failure, replay/live/fixtures explicitly labeled.

**Acceptance:** all section-29 checks; source-backed G4→G5 inspection; running-with-failure and partial-terminal fixtures; no passive result verification; no worker secrets; reconnect cursor deduplication; keyboard-complete workflow; documented live integration gaps.

**Screenshot / visual QA:** capture 1440×900, 1366×768, 1280×800, 1024×768 and 768×1024. Capture Job Detail with G5 accepted/G4 expired+VERIFIED+stale rejection, deadline-passed ACTIVE, FAILED job with partial acceptance, empty acceptance, disconnected last-known state, missing capability, integrity-read error, Worker lifecycle/liveness split and clearly labeled recorded Lab. Inspect focus, selected vs accepted styling, long IDs/versions, table overflow, drawer focus/return, 200% zoom and reduced motion. Fixture screenshots must display SYNTHETIC DEMO DATA. Do not claim these screenshots show a running deployment.

## Source index

Pinned repository prefix: https://github.com/ADITHYA-SANJEEVI/relay-contract/blob/bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc/

- [README](https://github.com/ADITHYA-SANJEEVI/relay-contract/blob/bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc/README.md): implemented M3 bounds, CLI behavior and local setup.
- [SPEC](https://github.com/ADITHYA-SANJEEVI/relay-contract/blob/bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc/docs/SPEC.md), [STATE_MACHINES](https://github.com/ADITHYA-SANJEEVI/relay-contract/blob/bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc/docs/STATE_MACHINES.md), [accepted amendments](https://github.com/ADITHYA-SANJEEVI/relay-contract/blob/bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc/docs/decisions/2026-10-02-m0-contract-amendments.md): authority, liveness, transitions and deferred incidents.
- [API implementation](https://github.com/ADITHYA-SANJEEVI/relay-contract/blob/bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc/src/relay/api/app.py), [models](https://github.com/ADITHYA-SANJEEVI/relay-contract/blob/bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc/src/relay/api/models.py): actual route/auth/field support.
- [Persistence](https://github.com/ADITHYA-SANJEEVI/relay-contract/blob/bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc/src/relay/db/schema.py), [publication](https://github.com/ADITHYA-SANJEEVI/relay-contract/blob/bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc/src/relay/control/publication.py), [leases](https://github.com/ADITHYA-SANJEEVI/relay-contract/blob/bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc/src/relay/control/leases.py): stored relations/events, acceptance/rejection, heartbeat observations.
- [Gateway](https://github.com/ADITHYA-SANJEEVI/relay-contract/blob/bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc/src/relay/artifacts/gateway.py), [recovery](https://github.com/ADITHYA-SANJEEVI/relay-contract/blob/bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc/src/relay/recovery/service.py), [worker](https://github.com/ADITHYA-SANJEEVI/relay-contract/blob/bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc/src/relay/worker/process.py): verification, expiry and available process behavior.
- [M3 evidence](https://github.com/ADITHYA-SANJEEVI/relay-contract/blob/bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc/docs/M3_EVIDENCE.md), [process tests](https://github.com/ADITHYA-SANJEEVI/relay-contract/blob/bf8ddccd6ace6384cbcc97513c3e30b1a3d05ccc/tests/faults/test_process_faults.py): recorded failure/recovery and generation-4/5 observations.

Earlier local proposal package: RELAY_PRODUCT_ARCHITECTURE.md, CONTROL_BOARD_INFORMATION_ARCHITECTURE.md, UI_API_GAP_ANALYSIS.md, OBSERVABILITY_CONTRACT.md, BENCHMARK_CONTRACT.md, ADVERSARIAL_MATRIX.md, DEMO_FAULT_CONTROL_BOUNDARY.md and TWO_PASS_FINISHING_PLAN.md. These guide proposed integration; they do not establish implemented capabilities.
