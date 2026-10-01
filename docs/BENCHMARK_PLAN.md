# Preregistered benchmark methodology

Version 1.0, frozen before implementation. **No results exist.** Parameter changes after a pilot require a dated amendment, reason and preservation of original runs. Do not choose only flattering worker counts, seeds, fault types or partition sizes.

## Workload and environment

Use SPEC's deterministic integer aggregation workload and a separately written serial oracle. Fixed generator seed 20261002, fixed schema/normalization version and published data-generation digest. Proposed main dataset: 8,000,000 records; pilot checks disk/RAM and runtime only, not which setup scales best. If infeasible on the actual machine, downsize once before measurements and record the amendment. Maintain minimum enough partitions for 8 workers: baseline 100,000 records/partition (80 partitions); sweep 25,000, 100,000 and 400,000 (320, 80, 20). Input shards are canonical and identical across compared runs. Partition output limits must pass preflight. Keep generated data and local volumes out of Git.

Record CPU model, physical/logical cores, RAM, OS/WSL/Docker versions, power mode, disk type/free space, host load, code commit, lockfile and image digests, resource limits, DB config, store config, lease/backoff/timeouts, workload digest and input hashes. One fixed total machine budget across worker counts; each worker runs one task process and native libraries use one compute thread unless explicitly changed in a separate experiment. Report any 8-worker oversubscription. API, DB, store and workers share hardware: measure them all. No remote services.

## Experiment matrix

| Experiment | Worker counts | Partition sizes | Fault rates/types |
|---|---|---|---|
| Scaling | 1, 2, 4, 8 | 100k records | 0% |
| Partition sweep | 1, 2, 4, 8 | 25k, 100k, 400k | 0% |
| Failure sweep | 1, 2, 4, 8 | 100k | 0%, 1%, 5%, 10%; separate kill and pause runs |
| Publication ambiguity | 1, 4, 8 | 100k | Drop post-commit reply for deterministic 5% first attempts |
| Scheduler fairness | 4, 8 | Mixed jobs: 1, 20, 80 partitions | No faults; continuous submissions plus one finite fixed cohort |

Scaling baseline duplicates in partition/failure matrix are reused by experiment identity, not silently counted as extra independent repetitions. Main cell has five measured runs after one excluded warmup. Fixed run seeds 101, 202, 303, 404, 505 define fault selection and randomized cell order. Preserve all valid runs and all failed runs with cause. Report median, min/max and all five observations; with five samples do not imply precise confidence intervals. Additional repeats only as a predeclared extension applied to every affected cell.

## Timing boundaries and cache policy

Primary end-to-end time begins immediately before POST /jobs and ends when GET /jobs first observes terminal state, with polling interval fixed 100ms and reported separately. Workers/services already ready; input generated/imported before timing. Include queueing, claim, execution, read/write, verification, retry and publication. Report input preparation/import and service startup separately. Also compute DB job created_at→finished_at as server duration; don't mix host and DB clocks in one subtraction.

Use a documented **warm-input-cache** protocol: preload the identical input once before each cell, one untimed job, then measured runs with fresh job/output keys and identical DB starting size class. No privileged cache dropping required. State explicitly that store/DB cache warmth may persist. Cold-start/cache study is optional and separate. Do not compare warm single-worker with cold eight-worker runs. Clean experimental volumes only between complete isolated batches, never during a running job. Keep manifests/metrics/traces before cleanup.

## Exact metric definitions

| Metric | Definition |
|---|---|
| Useful records/sec | Number of input records covered by successfully accepted partitions, counted once, divided by end-to-end seconds; invalid rows scanned still count, valid/invalid counts also reported |
| Partition throughput | Number of newly accepted partitions / end-to-end seconds |
| Speedup | Median 1-worker runtime / median N-worker runtime for identical workload and fault cell |
| Efficiency | Speedup / worker count; descriptive on shared machine |
| Partition end-to-end latency | Acceptance time − partition creation time, includes queue/backoff/retries; failed/cancelled partitions reported separately, never silently excluded |
| Attempt execution latency | Child compute start→finish monotonic duration, excluding queue/upload, labelled explicitly |
| p50/p95 | Nearest-rank percentiles of each run's relevant observations; show count, not average of percentiles presented as pooled data |
| Expiry detection latency | recovery EXPIRED event DB time − lease_expires_at |
| Recovery latency | Replacement claim DB time − expired attempt lease_expires_at; includes scan/backoff/queue. Also report recovered acceptance−expiry separately |
| Useful recovery throughput | Same useful records/sec, never all-attempt processed rows |
| Recomputation factor | Total records actually processed by all attempts / total unique input records; unfinished jobs denominator still full input and completion fraction shown |
| Extra-work fraction | (Total processed − uniquely accepted processed records) / total input records; distinguish computation still useful in unfinished jobs |
| Retry volume | Claims with generation>1; expiry events separately |
| Stale publication count | Distinct rejected publication request IDs with stale generation; lease-expired same-generation rejections separately |
| Incorrect authoritative outputs | Accepted partitions whose canonical output differs from oracle, plus missing/extra/duplicate coverage; all components reported |
| Resources | Per-service CPU seconds, peak and sampled memory, total cgroup memory, host CPU/memory, I/O bytes, DB lock waits; 1-second sample cadence |

Instrumentation must capture processed-row progress in acknowledged chunks at deterministic checkpoints. A killed process can lose unacknowledged progress; report measured lower/upper bounds using chunk size rather than fabricate exact recomputation. For the deterministic kill-at-chunk-boundary experiment, supervisor acknowledgment before kill permits exact completed-chunk counts. CPU work within a chunk is not equated to completed rows. Integrity/oracle check occurs after timed run and is mandatory; its cost is reported separately.

## Failure denominator and selection

The nominal fault percentage is **selected first attempts divided by the fixed number of logical partitions**, not a moving fraction of every retry attempt. For each seed rank partition ordinals by a deterministic hash; choose round_half_up(rate × partition_count). Report nominal rate, selected count, selected_count/partition_count and observed injected failures / all claimed attempts. With 80 partitions, 1% selects 1 (1.25% actual target fraction); never label it exact 1%. Retries are not recursively selected. This avoids a self-changing denominator and lets runs terminate. Separate repeated-failure/poison tests are correctness experiments, not these throughput cells.

Kill run: selected first attempt pauses at 50% acknowledged input progress; harness kills worker/container and immediately launches a replacement session. It waits for lease recovery before that partition can be claimed; replacement may do other work meanwhile. Pause run: selected attempt verifies output then pauses whole worker before publish; launch replacement capacity, expire/reassign, wait for successful replacement publication, resume old worker once to attempt stale publication, then stop the old session. Keep intended available worker capacity at N; record temporary extra frozen processes and resource impact. If replacement fails terminally, abort that fault scenario with trace, do not hang forever waiting at a barrier.

Kill runs normally produce no stale completion; do not claim stale rejection from killing alone. Pause runs explicitly exercise rejection. Post-commit reply-loss run retries exact identities and should create zero extra computation. For retry exhaustion and cancellation use separate correctness traces rather than blending them into a successful-throughput average.

## Validity and reporting gates

Hard gate: zero incorrect authoritative outputs, zero invariant violations, and no unexplained missing events. Any violation invalidates the correctness claim even if throughput improves. Report failed jobs and timeouts; maximum per measured run 30 minutes (preregistered), record censored duration and completion fraction rather than deleting it. Resource pressure is a finding. Do not impose invented linear-scaling or recovery SLA targets.

Export per-run configuration, input hashes, environment manifest, seed, timings, attempt history, fault schedule, event trace, metrics CSV, oracle comparison and summary JSON. Raw large metrics/artifacts live outside source control; commit small summaries/checksums/reproduction instructions. Human-readable report compares useful work with total work, shows all worker counts and partition sizes, and discusses the scheduler/job-lock bottleneck. No resume number until a command at a recorded commit reproduces its evidence.
