# M1A persistence evidence

Observed on the existing Windows checkout on 2 October 2026. Scope: M1A only. No API, execution, claim, renewal, publication, cancellation or recovery service is implemented.

## Starting state

- Root: `C:\Users\adith\OneDrive\Desktop\relay-contract`.
- Branch: `main`; clean starting HEAD: `f4c2f02f83f987407934f1b18936dc45e1b55093`.
- Existing private origin: `https://github.com/ADITHYA-SANJEEVI/relay-contract.git`.
- Starting M0 command: `.\.venv\Scripts\python.exe -m pytest tests/infrastructure tests/storage_contract -v -s --maxfail=1`: **12 passed in 3.11s**; zero failures, skips, xfails or warnings.
- Actual PostgreSQL: 18.6, `server_version_num=180006`; Python 3.12.10; psycopg 3.3.6. Existing PostgreSQL and MinIO Compose services were healthy. The M0 tests and their service configuration are unchanged.

## Migration and resulting database

`scripts/init_db.py` creates the separate `relay` database on the existing PostgreSQL instance, owned by infrastructure/migration identity `relay_m0`. It configures a separate `relay_runtime` login and stores its generated password only in ignored `.env`. Bootstrap was repeated successfully. Runtime has no superuser, database-create, role-create, replication or RLS-bypass flags and no role memberships. It owns none of the application tables. Migration authority is trusted and distinct; tests of runtime restrictions authenticate directly as `relay_runtime`, never by a superuser impersonation shortcut.

Alembic revision `0001_persistence` was applied successfully to `relay`; `alembic current` returned `0001_persistence (head)`. The migration creates all 13 contract tables, adds the deferred circular FK after attempts and partitions exist, installs guards/grants and seeds exactly scheduler `(id=1,next_ticket=1)`. Migration SQL is frozen and reviewable, separate from Core metadata; runtime never calls `create_all()`.

`test_clean_upgrade_downgrade_upgrade` exercised an empty UUID-named database: upgrade to head, inspect 13 tables plus Alembic's version table and singleton seed, downgrade to base, verify no Relay tables/functions remain, upgrade to head, repeat upgrade, verify one seed and the same head. All succeeded. Downgrade is destructive and was used only on the disposable database; bootstrap role configuration and public-schema privilege hardening persist independently of table downgrade. Test cleanup drops only databases created by that allocation fixture. M0 data and Docker volumes were retained.

An early migration run hit psycopg's percent-placeholder parsing in PL/pgSQL and rolled back. Both script executions now explicitly use SQLAlchemy's `no_parameters` option; subsequent real clean upgrades and roundtrips passed. Automatic approval review rejected an earlier proposed migration targeting the retained M0 database before execution. The target was corrected to the separate `relay` database; that operation was approved and completed.

Actual deployed schema inspection returned **no metadata differences** for column types, nullability, defaults, keys and indexes. Catalog inspection found 51 CHECKs, 21 FKs, 14 UNIQUE constraints and 39 enabled noninternal triggers. There are 13 Relay PKs plus Alembic's PK. Five consistency triggers are DEFERRABLE INITIALLY DEFERRED; no guard function is SECURITY DEFINER. The latest-attempt FK is DEFERRABLE INITIALLY DEFERRED, and the events attempt FK uses MATCH FULL. All FKs restrict history deletion. The 13 explicit indexes, including both partial unique ACTIVE indexes, were inspected from `pg_indexes` in the deployed database.

## Table coverage and runtime permissions

Runtime has SELECT on every application table and no DELETE/TRUNCATE on any. INSERT/UPDATE are available on mutable entities as specified, with guards rejecting immutable updates. Append-only relations have SELECT/INSERT only; scheduler has SELECT/UPDATE only. Runtime has no Alembic-table grants, schema CREATE authority or ability to alter tables, disable triggers, switch to the migration role or change `session_replication_role`.

| Table (all created) | Important inspected enforcement/indexes | Runtime restrictions |
|---|---|---|
| jobs | UUID PK; parent self-FK; version/status/policy/count/hash checks; immutable definition/policy; active fair-ticket index; deferred terminal/count check; definition hash deliberately nonunique | Guarded INSERT/UPDATE; terminal reopening blocked |
| input_artifacts | UUID PK; unique import key and object key; unique bucket/key/version; expected/verified identity and VERIFIED checks; reconciliation index | Identity immutable; VERIFIED/REJECTED metadata frozen |
| job_inputs | Composite job/ordinal PK; job/input FKs; unique job/input; only VERIFIED inputs attach | Insert only during job creation; all updates rejected |
| partitions | UUID PK; job FK; unique job/ordinal and id/job; generation projection CHECK and deferred latest-attempt FK; READY and job/status indexes; state/history/commit guards | Identity immutable; terminal reopening blocked; insertion only during job creation |
| partition_inputs | Composite partition/slice PK; exact partition/job and job/input composite FKs; nonnegative slice/range fields | Insertion only during job creation; all updates rejected |
| workers | Session UUID PK; state/hash/counter checks; session event sequence; liveness index; stopped/ACTIVE consistency | Identity immutable; terminal state cannot reopen; display name deliberately nonunique |
| attempts | UUID PK; partition/worker FKs; unique partition/generation and id/partition/generation; partial unique ACTIVE partition and worker indexes; expiry index; deadline checks and immutable owner/hard deadline | Guarded INSERT/UPDATE; terminal metadata frozen |
| artifacts | UUID PK; exact attempt/partition/generation composite FK; unique attempt, composite identity, bucket/key and bucket/key/version; expected/verified equality and output-size checks; reconciliation index | Identity/expectations immutable; VERIFIED/REJECTED frozen |
| accepted_results | Partition PK; unique attempt/artifact; exact attempt and artifact composite FKs; latest-success/VERIFIED deferred check; no status | SELECT/INSERT; UPDATE/DELETE denied; owner ordinary DML also hits history guard |
| events | Job/seq PK; job FK; partition/job composite FK; optional attempt MATCH FULL FK and all-or-none/partition checks; cursor index | SELECT/INSERT only; append-only |
| worker_events | Session/seq PK; worker FK; positive sequence; cursor index | SELECT/INSERT only; append-only |
| request_receipts | Scope/key PK; key length 1–128; hash/status checks; nullable identity FKs; JSONB response; job and worker indexes | SELECT/INSERT only; immutable receipt |
| scheduler_state | Integer PK CHECK id=1; positive bigint next_ticket; migration seed `(1,1)` | SELECT/UPDATE only; cannot insert/delete/truncate |

`jobs.creation_xid` is a minimal internal guard-support column: the insert trigger sets the PostgreSQL creation transaction identity and immutable-column protection prevents replacement. Manifest rows must be inserted in that same transaction. It is never ownership, generation, time, scheduling or an API field. Using mutable row `xmin` instead would let an ordinary later job UPDATE reopen manifest insertion; `test_manifest_late_insert_rejected` specifically attempts that update followed by insertion and proves rejection. No manifest coverage validator is claimed.

## Negative DML evidence

These are actual PostgreSQL outcomes. Parameterized cases are separate pytest items. `rejected()` asserts the SQLSTATE and, where given, the exact named constraint. Deferred tests set a flag after all statements succeed, require failure on transaction-scope COMMIT, and selected tests read back original state to verify rollback.

| Test | Attempted operation | Observed result |
|---|---|---|
| test_duplicate_partition_ordinal | Insert second ordinal in same job | 23505 `uq_partitions_job_id_ordinal` |
| test_duplicate_attempt_generation | Insert repeated partition/generation | 23505 `uq_attempts_partition_id_generation` |
| test_second_active_ownership | Second ACTIVE partition or worker owner | 23505 `uq_attempts_active_partition` / `uq_attempts_active_worker` |
| test_cross_identity_bindings | Wrong artifact partition/generation; wrong accepted attempt/generation/artifact | 23503 corresponding exact composite FK |
| test_one_output_artifact_per_attempt | Second output for attempt | 23505 `uq_artifacts_attempt_id` |
| test_generation_zero_projection / test_positive_generation_projection | Nonnull projection at zero; null/unequal projection at positive generation | 23514 `ck_partitions_generation_projection`; valid zero/NULL read back |
| test_missing_latest_attempt_fails_at_commit | Update partition to generation 1 without attempt | Statements succeeded; COMMIT 23503 `fk_partitions_latest_attempt`; original READY/0 retained |
| test_generation_budget_fails_at_commit | Second recorded claim with max_attempts=1 | Statements succeeded; COMMIT 23514 `relay_partition_consistency`; generation remains 1 |
| test_latest_generation_history_fails_at_commit | Record newer attempt without advancing projection | Statements succeeded; COMMIT 23514 `relay_partition_consistency` |
| test_duplicate_accepted_result | Second acceptance for same partition | 23505 `pk_accepted_results` |
| test_unverified_accepted_artifact_fails_at_commit | Settle SUCCEEDED with RESERVED artifact | Statements succeeded; COMMIT 23514 `relay_accepted_consistency`; no result committed |
| test_partition_commit_consistency | READY/FAILED/CANCELLED/SUCCEEDED with latest ACTIVE attempt | Statements succeeded; COMMIT 23514 `relay_partition_consistency` |
| test_terminal_reopening / test_other_terminal_reopening / test_invalid_state_edge | Reopen terminal job/partition/attempt/worker/input/artifact, or invalid QUEUED/READY→FAILED edge | 23514 `relay_state_transition` |
| test_job_terminal_consistency_at_commit / test_nonterminal_job_all_terminal_fails_at_commit / test_partition_count_fails_at_commit | Inconsistent job terminal state or wrong partition count | Statements succeeded; COMMIT 23514 `relay_job_consistency` |
| test_immutable_columns | Change job definition/policy, identities, owner, generation or artifact expectation | 23514 `relay_immutable_column` |
| test_terminal_metadata_immutable | Change verified version/hash/count or terminal attempt metadata | 23514 `relay_state_transition` |
| test_manifest_late_insert_rejected / test_manifest_update_rejected | Later partition/input/slice insertion, including after job UPDATE; relation UPDATE | 23514 `relay_manifest_frozen` / `relay_immutable_history` |
| test_only_verified_inputs_attach / test_partition_manifest_cross_job_binding | Attach RESERVED input; slice for another job's partition | 23514 `relay_input_verified` / 23503 `fk_partition_inputs_partition_job` |
| test_runtime_append_only_denied | UPDATE/DELETE populated results/events/worker-events/receipts | 42501 insufficient privilege |
| test_runtime_cannot_delete_or_truncate_history | DELETE and TRUNCATE every contract table | 42501 insufficient privilege |
| test_runtime_cannot_bypass_guards | Disable triggers, drop constraint, change replication role, create schema table, SET ROLE admin | 42501 insufficient privilege |
| test_migration_owner_ordinary_dml_still_hits_history_trigger | Owner UPDATE/DELETE populated accepted result | 23514 `relay_immutable_history`; explicitly an owner test |
| test_verified_fields_required / test_verified_artifact_expected_match | VERIFY with missing fields or mismatched SHA | 23514 named VERIFIED CHECK |
| test_invalid_event_bindings | Partial attempt tuple, wrong job/attempt or absent partition | 23514 optional/partition CHECK or 23503 composite FK |
| test_job_domain_bounds / test_receipt_key_bound / test_scheduler_singleton | Invalid policy/count/hash/counter, oversized/empty key or singleton/ticket | 23514 named CHECK; 129-character key gives 22001 |
| test_lease_cannot_exceed_hard_deadline / test_hard_deadline_policy_at_commit | Lease exceeds hard deadline; hard deadline disagrees with policy | Immediate 23514 deadline CHECK / COMMIT 23514 `relay_hard_deadline` |
| test_stopped_worker_cannot_retain_active_at_commit | STOPPED worker retains ACTIVE attempt | Statements succeeded; COMMIT 23514 `relay_worker_consistency` |

Positive fixtures also committed a consistent accepted-result graph, generation-zero job creation, verified reusable input/slice relations and job-only/partition-only/attempt events. Identical job definition hashes and worker display names were accepted. These are test DML fixtures, not implementations of submit/claim/verify/publish.

## Tests and dependency locking

```powershell
Set-Location "C:\Users\adith\OneDrive\Desktop\relay-contract"
.\.venv\Scripts\uv.exe lock --check --offline --cache-dir .cache/uv
.\.venv\Scripts\python.exe -m pytest tests/persistence -v -s --maxfail=1
.\.venv\Scripts\python.exe -m pytest tests/infrastructure tests/storage_contract -v -s --maxfail=1
```

- Expanded M1A suite: **122 passed**, zero failed/skipped/xfailed; no pytest warnings.
- After M1A, unchanged M0 suite: **12 passed**, zero failed/skipped/xfailed; no pytest warnings. M0 results remain distinct from M1A.
- Added direct dependencies: SQLAlchemy **2.1.1**, Alembic **1.20.0**.
- Newly added transitive packages: Mako **1.4.3**, MarkupSafe **3.0.3**. No existing M0 dependency was upgraded. `uv.lock` retains pinned distribution hashes.
- The runtime engine test verified psycopg, READ COMMITTED, synchronous_commit=on, 2s/5s/5s timeouts, actual FOR UPDATE and exception rollback. Missing runtime credentials raise instead of falling back to migration authority.

## Enforcement boundary and future obligations

PostgreSQL fully enforces keys, exact composite identities, domain/projection/deadline CHECKs, partial unique ACTIVE cardinality, immutable fields/history, status edges and runtime privilege restrictions. The real tests prove the listed invalid DML is rejected.

Migration-owned deferred triggers enforce affected-job/partition/worker consistency in the committing transaction's view. They are database protections, not transition services or automatic concurrency serialization. Full concurrent operation correctness additionally requires the single transition service to lock scheduler/job/partitions/attempts/worker/artifact/receipt in the documented order. READ COMMITTED cross-table reads alone do not replace those locks. Concurrent ownership/lease/publication/recovery races have not been tested or claimed in M1A.

Later services must authenticate owners; qualify all IDs; apply the canonical live-attempt-ownership predicate with one fresh post-lock DB-time sample; gate mutation by affected-row count; allocate fair tickets/events/receipts atomically; validate fingerprint replay and retries; enforce submission coverage/schema/descriptor and worker-capacity limits; classify failure and backoff; verify actual object bytes/version/schema outside DB locks; return success only after commit and handle unknown outcomes. CHECKs on verified metadata do not prove object-store integrity. Event/receipt JSONB and failure detail are present; the contract supplies no numeric detail bound, so API validation must define/apply its permitted bounded representation without inventing a database limit here. The specified descriptor/output limits still apply to future operations.

No unresolved M1A implementation failure is observed. Retained services/volumes, trusted local migration authority and runtime-only application connections remain prerequisites. The strongest established claim is the contract-defined PostgreSQL persistence foundation and the recorded structural/constraint evidence. M1B has not started.
