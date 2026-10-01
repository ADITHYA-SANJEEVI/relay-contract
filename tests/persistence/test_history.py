from uuid import uuid4

import pytest
from psycopg import sql

from relay.db.schema import metadata

from .helpers import (HASH, OTHER_HASH, accepted_rows, active_rows, artifact_row,
                      event_row, input_row, insert, job_rows, rejected, update, worker_row)


@pytest.mark.parametrize("table,field,value", [
    ("jobs", "definition_hash", OTHER_HASH), ("jobs", "parameters", {"changed": True}),
    ("jobs", "max_attempts", 4), ("jobs", "manifest_hash", OTHER_HASH),
    ("jobs", "creation_xid", "forged"), ("partitions", "ordinal", 7),
    ("workers", "session_secret_hash", OTHER_HASH), ("workers", "display_name", "changed"),
    ("attempts", "worker_session_id", uuid4()), ("attempts", "generation", 2),
    ("input_artifacts", "expected_sha256", OTHER_HASH), ("input_artifacts", "object_key", "changed"),
    ("artifacts", "expected_size_bytes", 11), ("artifacts", "attempt_id", uuid4()),
])
def test_immutable_columns(runtime, table, field, value):
    with runtime.transaction():
        job, parts, worker, attempt = active_rows(runtime)
        input_id = input_row(runtime, verified=False)
        artifact = artifact_row(runtime, parts[0], attempt, verified=False)
    identities = {"jobs": ("id", job), "partitions": ("id", parts[0]), "workers": ("session_id", worker),
                  "attempts": ("id", attempt), "input_artifacts": ("id", input_id), "artifacts": ("id", artifact)}
    with rejected("23514", constraint="relay_immutable_column"):
        update(runtime, table, identities[table], **{field: value})


@pytest.mark.parametrize("table,field,value", [("artifacts", "object_version", "different"),
    ("artifacts", "verified_sha256", OTHER_HASH), ("input_artifacts", "row_count", 2),
    ("input_artifacts", "object_version", "different"), ("attempts", "last_renew_seq", 1)])
def test_terminal_metadata_immutable(runtime, table, field, value):
    with runtime.transaction():
        job, part, worker, attempt, artifact = accepted_rows(runtime)
        input_id = input_row(runtime)
    identity = {"artifacts": artifact, "input_artifacts": input_id, "attempts": attempt}[table]
    with rejected("23514", constraint="relay_state_transition"):
        update(runtime, table, ("id", identity), **{field: value})


@pytest.mark.parametrize("table", ["attempts", "workers", "input_artifacts", "artifacts"])
def test_other_terminal_reopening(runtime, table):
    with runtime.transaction():
        job, part, worker, attempt, artifact = accepted_rows(runtime)
        input_id = input_row(runtime)
        update(runtime, "workers", ("session_id", worker), state="STOPPED")
    identities = {"attempts": ("id", attempt), "workers": ("session_id", worker),
                  "input_artifacts": ("id", input_id), "artifacts": ("id", artifact)}
    with rejected("23514", constraint="relay_state_transition"):
        update(runtime, table, identities[table], **({"state": "REGISTERED"} if table == "workers"
               else {"status": "ACTIVE" if table == "attempts" else "RESERVED"}))


@pytest.mark.parametrize("table", ["partitions", "job_inputs", "partition_inputs"])
def test_manifest_late_insert_rejected(runtime, table):
    with runtime.transaction():
        job, parts = job_rows(runtime, with_input=True)
        extra_input = input_row(runtime)
    with rejected("23514", constraint="relay_manifest_frozen"):
        with runtime.transaction():
            # Updating jobs gives it a new xmin, but cannot change creation_xid.
            runtime.execute("UPDATE jobs SET next_event_seq=next_event_seq+1 WHERE id=%s", (job,))
            if table == "partitions":
                insert(runtime, table, id=uuid4(), job_id=job, ordinal=1)
            elif table == "job_inputs":
                insert(runtime, table, job_id=job, input_ordinal=1, input_artifact_id=extra_input)
            else:
                insert(runtime, table, partition_id=parts[0], job_id=job, slice_ordinal=1,
                       input_ordinal=0, first_row=0, row_count=0)


def test_only_verified_inputs_attach(runtime):
    with rejected("23514", constraint="relay_input_verified"):
        with runtime.transaction():
            job, parts = job_rows(runtime)
            input_id = input_row(runtime, verified=False)
            insert(runtime, "job_inputs", job_id=job, input_ordinal=0, input_artifact_id=input_id)


@pytest.mark.parametrize("table", ["job_inputs", "partition_inputs"])
def test_manifest_update_rejected(runtime, table):
    with runtime.transaction():
        job, parts = job_rows(runtime, with_input=True)
    with rejected("23514", constraint="relay_immutable_history"):
        runtime.execute(sql.SQL("UPDATE {} SET created_at=created_at WHERE job_id=%s").format(sql.Identifier(table)), (job,))


@pytest.mark.parametrize("table", ["accepted_results", "events", "worker_events", "request_receipts"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_runtime_append_only_denied(runtime, table, operation):
    with runtime.transaction():
        job, part, worker, attempt, artifact = accepted_rows(runtime)
        event_row(runtime, job)
        insert(runtime, "worker_events", session_id=worker, seq=1, type="FIXTURE", details={})
        insert(runtime, "request_receipts", scope="fixture", key=str(job), request_hash=HASH,
               operation="fixture", job_id=job, status_code=200, response={})
    with rejected("42501"):
        if operation == "DELETE":
            runtime.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))
        else:
            field = "publication_fingerprint" if table == "accepted_results" else "type" if table != "request_receipts" else "operation"
            runtime.execute(sql.SQL("UPDATE {} SET {}={}").format(sql.Identifier(table), sql.Identifier(field), sql.Identifier(field)))


@pytest.mark.parametrize("table", list(metadata.tables))
def test_runtime_cannot_delete_or_truncate_history(runtime, table):
    for operation in ("DELETE FROM", "TRUNCATE"):
        with rejected("42501"):
            runtime.execute(sql.SQL("{} {}").format(sql.SQL(operation), sql.Identifier(table)))


@pytest.mark.parametrize("operation", ["ALTER TABLE jobs DISABLE TRIGGER ALL",
    "SET session_replication_role = replica", "CREATE TABLE public.runtime_bypass (id int)",
    "ALTER TABLE jobs DROP CONSTRAINT ck_jobs_version", "SET ROLE relay_m0"])
def test_runtime_cannot_bypass_guards(runtime, operation):
    with rejected("42501"):
        runtime.execute(operation)


def test_runtime_privilege_catalog(runtime):
    assert runtime.execute("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls "
                           "FROM pg_roles WHERE rolname=current_user").fetchone() == (False,) * 5
    assert runtime.execute("SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member "
                           "WHERE r.rolname=current_user").fetchone()[0] == 0
    for table in metadata.tables:
        owner, select, delete, truncate = runtime.execute("SELECT pg_get_userbyid(c.relowner),"
            "has_table_privilege(current_user,c.oid,'SELECT'),has_table_privilege(current_user,c.oid,'DELETE'),"
            "has_table_privilege(current_user,c.oid,'TRUNCATE') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relname=%s", (table,)).fetchone()
        assert owner == "relay_m0" and select and not delete and not truncate
    assert not runtime.execute("SELECT has_table_privilege('relay_runtime','alembic_version','SELECT')").fetchone()[0]
    print("Actual runtime identity: no administrative flags/memberships/ownership or history DELETE/TRUNCATE grants")


def test_migration_owner_ordinary_dml_still_hits_history_trigger(db_connect):
    with db_connect() as c:
        with c.transaction():
            job, part, worker, attempt, artifact = accepted_rows(c)
    with db_connect(admin=True) as c:
        with rejected("23514", constraint="relay_immutable_history"):
            c.execute("UPDATE accepted_results SET publication_fingerprint=%s WHERE partition_id=%s", (OTHER_HASH, part))
        with rejected("23514", constraint="relay_immutable_history"):
            c.execute("DELETE FROM accepted_results WHERE partition_id=%s", (part,))


def test_stopped_worker_cannot_retain_active_at_commit(runtime):
    with runtime.transaction():
        job, parts, worker, attempt = active_rows(runtime)
    statement_succeeded = False
    with rejected("23514", constraint="relay_worker_consistency", deferred=True):
        with runtime.transaction():
            update(runtime, "workers", ("session_id", worker), state="STOPPED")
            statement_succeeded = True
    assert statement_succeeded


def test_scheduler_singleton(runtime):
    assert runtime.execute("SELECT id,next_ticket FROM scheduler_state").fetchall() == [(1, 1)]
    with rejected("23514", constraint="ck_scheduler_state_singleton"):
        runtime.execute("UPDATE scheduler_state SET id=2 WHERE id=1")
    with rejected("23514", constraint="ck_scheduler_state_ticket"):
        runtime.execute("UPDATE scheduler_state SET next_ticket=0 WHERE id=1")


@pytest.mark.parametrize("key,code", [("", "23514"), ("x" * 129, "22001")])
def test_receipt_key_bound(runtime, key, code):
    with rejected(code):
        insert(runtime, "request_receipts", scope="fixture", key=key, request_hash=HASH,
               operation="fixture", status_code=200, response={})
