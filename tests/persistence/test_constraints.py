from datetime import timedelta
from uuid import uuid4

import pytest

from .helpers import (HASH, OTHER_HASH, accepted_rows, active_rows, artifact_row,
                      attempt_row, event_row, finish_rows, input_row, insert,
                      job_rows, rejected, update, worker_row)


def test_duplicate_partition_ordinal(runtime):
    with rejected("23505", constraint="uq_partitions_job_id_ordinal"):
        with runtime.transaction():
            job, parts = job_rows(runtime)
            insert(runtime, "partitions", id=uuid4(), job_id=job, ordinal=0)


def test_duplicate_attempt_generation(runtime):
    with rejected("23505", constraint="uq_attempts_partition_id_generation"):
        with runtime.transaction():
            job, parts, worker, attempt = active_rows(runtime)
            attempt_row(runtime, parts[0], worker_row(runtime))


@pytest.mark.parametrize("scope,index", [("partition", "uq_attempts_active_partition"),
                                         ("worker", "uq_attempts_active_worker")])
def test_second_active_ownership(runtime, scope, index):
    with runtime.transaction():
        job, parts, worker, attempt = active_rows(runtime, count=2)
    with rejected("23505", constraint=index):
        with runtime.transaction():
            if scope == "partition":
                attempt_row(runtime, parts[0], worker_row(runtime), generation=2)
            else:
                update(runtime, "partitions", ("id", parts[1]), status="RUNNING", generation=1, latest_generation_fk=1)
                attempt_row(runtime, parts[1], worker)


@pytest.mark.parametrize("binding", ["artifact_partition", "artifact_generation", "result_attempt", "result_generation", "result_artifact"])
def test_cross_identity_bindings(runtime, binding):
    with runtime.transaction():
        job, parts, worker, attempt = active_rows(runtime, count=2)
        artifact = artifact_row(runtime, parts[0], attempt)
    with rejected("23503"):
        with runtime.transaction():
            if binding.startswith("artifact"):
                # A new attempt avoids the one-artifact-per-attempt uniqueness barrier.
                update(runtime, "partitions", ("id", parts[1]), status="RUNNING", generation=1, latest_generation_fk=1)
                other_attempt = attempt_row(runtime, parts[1], worker_row(runtime))
                artifact_row(runtime, parts[0] if binding == "artifact_partition" else parts[1],
                             other_attempt, generation=2 if binding == "artifact_generation" else 1)
            else:
                insert(runtime, "accepted_results", partition_id=parts[1] if binding == "result_attempt" else parts[0],
                       attempt_id=attempt, generation=2 if binding == "result_generation" else 1,
                       artifact_id=uuid4() if binding == "result_artifact" else artifact,
                       publication_fingerprint=HASH)


def test_generation_zero_projection(runtime):
    with runtime.transaction():
        job, parts = job_rows(runtime)
    assert runtime.execute("SELECT generation,latest_generation_fk FROM partitions WHERE id=%s", (parts[0],)).fetchone() == (0, None)
    with rejected("23514", constraint="ck_partitions_generation_projection"):
        update(runtime, "partitions", ("id", parts[0]), latest_generation_fk=1)


@pytest.mark.parametrize("projection", [None, 2])
def test_positive_generation_projection(runtime, projection):
    with runtime.transaction():
        job, parts = job_rows(runtime)
    with rejected("23514", constraint="ck_partitions_generation_projection"):
        with runtime.transaction():
            update(runtime, "partitions", ("id", parts[0]), status="RUNNING", generation=1, latest_generation_fk=projection)


def test_missing_latest_attempt_fails_at_commit(runtime):
    with runtime.transaction():
        job, parts = job_rows(runtime)
    statement_succeeded = False
    with rejected("23503", constraint="fk_partitions_latest_attempt", deferred=True):
        with runtime.transaction():
            update(runtime, "jobs", ("id", job), status="RUNNING")
            update(runtime, "partitions", ("id", parts[0]), status="RUNNING", generation=1, latest_generation_fk=1)
            statement_succeeded = True
    assert statement_succeeded
    assert runtime.execute("SELECT status,generation FROM partitions WHERE id=%s", (parts[0],)).fetchone() == ("READY", 0)


def test_generation_budget_fails_at_commit(runtime):
    with runtime.transaction():
        job, parts, worker, attempt = active_rows(runtime, max_attempts=1)
    with runtime.transaction():
        update(runtime, "attempts", ("id", attempt), status="FAILED")
        update(runtime, "partitions", ("id", parts[0]), status="READY")
    statement_succeeded = False
    with rejected("23514", constraint="relay_partition_consistency", deferred=True):
        with runtime.transaction():
            update(runtime, "partitions", ("id", parts[0]), status="RUNNING", generation=2, latest_generation_fk=2)
            attempt_row(runtime, parts[0], worker, generation=2)
            statement_succeeded = True
    assert statement_succeeded
    assert runtime.execute("SELECT generation FROM partitions WHERE id=%s", (parts[0],)).fetchone()[0] == 1


def test_duplicate_accepted_result(runtime):
    with runtime.transaction():
        job, part, worker, attempt, artifact = accepted_rows(runtime)
    with rejected("23505", constraint="pk_accepted_results"):
        insert(runtime, "accepted_results", partition_id=part, attempt_id=attempt,
               generation=1, artifact_id=artifact, publication_fingerprint=HASH)


def test_unverified_accepted_artifact_fails_at_commit(runtime):
    with runtime.transaction():
        job, parts, worker, attempt = active_rows(runtime)
        artifact = artifact_row(runtime, parts[0], attempt, verified=False)
    statement_succeeded = False
    with rejected("23514", constraint="relay_accepted_consistency", deferred=True):
        with runtime.transaction():
            finish_rows(runtime, job, parts[0], attempt, artifact)
            statement_succeeded = True
    assert statement_succeeded
    assert runtime.execute("SELECT count(*) FROM accepted_results WHERE partition_id=%s", (parts[0],)).fetchone()[0] == 0


@pytest.mark.parametrize("status", ["READY", "FAILED", "CANCELLED", "SUCCEEDED"])
def test_partition_commit_consistency(runtime, status):
    with runtime.transaction():
        job, parts, worker, attempt = active_rows(runtime)
    statement_succeeded = False
    with rejected("23514", constraint="relay_partition_consistency", deferred=True):
        with runtime.transaction():
            update(runtime, "partitions", ("id", parts[0]), status=status)
            statement_succeeded = True
    assert statement_succeeded


@pytest.mark.parametrize("table,column", [("jobs", "id"), ("partitions", "id")])
def test_terminal_reopening(runtime, table, column):
    with runtime.transaction():
        job, part, worker, attempt, artifact = accepted_rows(runtime)
    with rejected("23514", constraint="relay_state_transition"):
        update(runtime, table, (column, job if table == "jobs" else part), status="RUNNING")


@pytest.mark.parametrize("table,target", [("jobs", "FAILED"), ("partitions", "FAILED")])
def test_invalid_state_edge(runtime, table, target):
    with runtime.transaction():
        job, parts = job_rows(runtime)
    with rejected("23514", constraint="relay_state_transition"):
        update(runtime, table, ("id", job if table == "jobs" else parts[0]), status=target)


@pytest.mark.parametrize("status", ["SUCCEEDED", "FAILED", "CANCELLED"])
def test_job_terminal_consistency_at_commit(runtime, status):
    with runtime.transaction():
        job, parts, worker, attempt = active_rows(runtime)
    statement_succeeded = False
    with rejected("23514", constraint="relay_job_consistency", deferred=True):
        with runtime.transaction():
            update(runtime, "jobs", ("id", job), status=status)
            statement_succeeded = True
    assert statement_succeeded


def test_nonterminal_job_all_terminal_fails_at_commit(runtime):
    with runtime.transaction():
        job, parts, worker, attempt = active_rows(runtime)
    statement_succeeded = False
    with rejected("23514", constraint="relay_job_consistency", deferred=True):
        with runtime.transaction():
            update(runtime, "attempts", ("id", attempt), status="FAILED")
            update(runtime, "partitions", ("id", parts[0]), status="FAILED")
            statement_succeeded = True
    assert statement_succeeded


def test_latest_generation_history_fails_at_commit(runtime):
    with runtime.transaction():
        job, parts, worker, attempt = active_rows(runtime)
    statement_succeeded = False
    with rejected("23514", constraint="relay_partition_consistency", deferred=True):
        with runtime.transaction():
            update(runtime, "attempts", ("id", attempt), status="FAILED")
            attempt_row(runtime, parts[0], worker_row(runtime), generation=2, status="ACTIVE")
            statement_succeeded = True
    assert statement_succeeded


@pytest.mark.parametrize("table", ["input_artifacts", "artifacts"])
def test_verified_fields_required(runtime, table):
    with runtime.transaction():
        if table == "input_artifacts":
            identity = input_row(runtime, verified=False)
        else:
            job, parts, worker, attempt = active_rows(runtime)
            identity = artifact_row(runtime, parts[0], attempt, verified=False)
    with rejected("23514", constraint=f"ck_{table}_verified"):
        update(runtime, table, ("id", identity), status="VERIFIED")


def test_verified_artifact_expected_match(runtime):
    with runtime.transaction():
        job, parts, worker, attempt = active_rows(runtime)
        artifact = artifact_row(runtime, parts[0], attempt, verified=False)
    with rejected("23514", constraint="ck_artifacts_verified"):
        runtime.execute("UPDATE artifacts SET status='VERIFIED',object_version='v',verified_sha256=%s,"
                        "verified_size_bytes=10,verified_schema_hash=%s,verified_at=clock_timestamp() WHERE id=%s",
                        (OTHER_HASH, HASH, artifact))


@pytest.mark.parametrize("kind", ["job_only", "partition_only", "attempt"])
def test_valid_event_optional_bindings(runtime, kind):
    with runtime.transaction():
        job, parts, worker, attempt = active_rows(runtime)
        fields = {} if kind == "job_only" else dict(partition_id=parts[0])
        if kind == "attempt":
            fields.update(attempt_id=attempt, attempt_partition_id=parts[0], attempt_generation=1)
        event_row(runtime, job, **fields)


@pytest.mark.parametrize("kind,code", [("partial_attempt", "23514"), ("wrong_job", "23503"),
                                      ("wrong_attempt", "23503"), ("missing_partition", "23514")])
def test_invalid_event_bindings(runtime, kind, code):
    with runtime.transaction():
        job, parts, worker, attempt = active_rows(runtime)
        other_job, other_parts = job_rows(runtime)
    fields = dict(partition_id=parts[0], attempt_id=attempt, attempt_partition_id=parts[0], attempt_generation=1)
    if kind == "partial_attempt": fields["attempt_generation"] = None
    if kind == "wrong_job": fields["partition_id"] = other_parts[0]; fields["attempt_partition_id"] = other_parts[0]
    if kind == "wrong_attempt": fields["attempt_id"] = uuid4()
    if kind == "missing_partition": fields["partition_id"] = None
    with rejected(code):
        event_row(runtime, job, **fields)


@pytest.mark.parametrize("field,value", [("version", 2), ("max_attempts", 0), ("max_attempts", 11),
    ("partition_count", 0), ("partition_count", 4097), ("lease_seconds", 0),
    ("lease_seconds", 601), ("max_attempt_seconds", 59), ("max_attempt_seconds", 3601),
    ("definition_hash", "invalid"), ("fair_ticket", 0), ("next_event_seq", 0)])
def test_job_domain_bounds(runtime, field, value):
    with rejected("23514"):
        with runtime.transaction():
            # Insert the bad row directly; don't allocate thousands of fixture partitions.
            insert(runtime, "jobs", **(dict(id=uuid4(), definition_hash=HASH, workload_name="test", workload_version="1",
                workload_digest=HASH, parameters={}, manifest_hash=HASH, partition_count=1, fair_ticket=1) | {field: value}))


def test_duplicate_definition_and_display_name_allowed(runtime):
    with runtime.transaction():
        job_rows(runtime); job_rows(runtime)
        first, second = worker_row(runtime), worker_row(runtime)
    assert first != second


def test_lease_cannot_exceed_hard_deadline(runtime):
    with runtime.transaction():
        job, parts, worker, attempt = active_rows(runtime)
    with rejected("23514", constraint="ck_attempts_deadlines"):
        runtime.execute("UPDATE attempts SET lease_expires_at=hard_deadline_at+interval '1 second' WHERE id=%s", (attempt,))


def test_hard_deadline_policy_at_commit(runtime):
    statement_succeeded = False
    with rejected("23514", constraint="relay_hard_deadline", deferred=True):
        with runtime.transaction():
            job, parts = job_rows(runtime)
            update(runtime, "jobs", ("id", job), status="RUNNING")
            update(runtime, "partitions", ("id", parts[0]), status="RUNNING", generation=1, latest_generation_fk=1)
            now = runtime.execute("SELECT clock_timestamp()").fetchone()[0]
            attempt_row(runtime, parts[0], worker_row(runtime), claimed_at=now,
                        lease_expires_at=now+timedelta(seconds=30), hard_deadline_at=now+timedelta(seconds=601))
            statement_succeeded = True
    assert statement_succeeded


def test_partition_manifest_cross_job_binding(runtime):
    with rejected("23503", constraint="fk_partition_inputs_partition_job"):
        with runtime.transaction():
            first, first_parts = job_rows(runtime, with_input=True)
            second, second_parts = job_rows(runtime, with_input=True)
            insert(runtime, "partition_inputs", partition_id=first_parts[0], slice_ordinal=1,
                   job_id=second, input_ordinal=0, first_row=0, row_count=1)


def test_one_output_artifact_per_attempt(runtime):
    with runtime.transaction():
        job, parts, worker, attempt = active_rows(runtime)
        artifact_row(runtime, parts[0], attempt)
    with rejected("23505", constraint="uq_artifacts_attempt_id"):
        artifact_row(runtime, parts[0], attempt)


def test_partition_count_fails_at_commit(runtime):
    statement_succeeded = False
    with rejected("23514", constraint="relay_job_consistency", deferred=True):
        with runtime.transaction():
            job_rows(runtime, count=1, partition_count=2)
            statement_succeeded = True
    assert statement_succeeded
