"""Small DML fixtures, deliberately outside runtime code."""

from contextlib import contextmanager
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

HASH = "a" * 64
OTHER_HASH = "b" * 64


def insert(connection, table, **values):
    connection.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, values)),
            sql.SQL(", ").join(sql.Placeholder() for _ in values),
        ),
        [Jsonb(value) if isinstance(value, dict) else value for value in values.values()],
    )


def update(connection, table, identity, **values):
    connection.execute(
        sql.SQL("UPDATE {} SET {} WHERE {} = %s").format(
            sql.Identifier(table),
            sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(k)) for k in values),
            sql.Identifier(identity[0]),
        ),
        [Jsonb(v) if isinstance(v, dict) else v for v in values.values()] + [identity[1]],
    )


@contextmanager
def rejected(code, *, constraint=None, deferred=False):
    """Require an actual PostgreSQL exception; print its exact SQLSTATE/name."""
    with pytest.raises(psycopg.Error) as caught:
        yield
    assert caught.value.sqlstate == code, str(caught.value)
    actual = caught.value.diag.constraint_name
    if constraint is not None:
        assert actual == constraint
    print(f"REJECTED {'COMMIT' if deferred else 'statement'} SQLSTATE={code} constraint={actual}")


def input_row(c, *, verified=True, **overrides):
    identity = uuid4()
    values = dict(id=identity, import_key=str(identity), reservation_fingerprint=HASH,
                  expected_sha256=HASH, size_bytes=10, media_type="test/opaque",
                  schema_hash=HASH, bucket="fixture", object_key=str(identity))
    values.update(overrides)
    insert(c, "input_artifacts", **values)
    if verified:
        c.execute("UPDATE input_artifacts SET status='VERIFIED', object_version='opaque-v1', "
                  "sha256=expected_sha256, row_count=1, verified_at=clock_timestamp() WHERE id=%s", (identity,))
    return identity


def job_rows(c, *, count=1, with_input=False, **overrides):
    job = uuid4()
    values = dict(id=job, definition_hash=HASH, workload_name="fixture", workload_version="1",
                  workload_digest=HASH, parameters={}, manifest_hash=HASH, partition_count=count, fair_ticket=1)
    values.update(overrides)
    insert(c, "jobs", **values)
    partitions = [uuid4() for _ in range(count)]
    for ordinal, partition in enumerate(partitions):
        insert(c, "partitions", id=partition, job_id=job, ordinal=ordinal)
    if with_input:
        input_id = input_row(c)
        insert(c, "job_inputs", job_id=job, input_ordinal=0, input_artifact_id=input_id)
        insert(c, "partition_inputs", partition_id=partitions[0], slice_ordinal=0,
               job_id=job, input_ordinal=0, first_row=0, row_count=1)
    return job, partitions


def worker_row(c, **overrides):
    worker = uuid4()
    values = dict(session_id=worker, display_name="reusable-name", registration_hash=HASH,
                  session_secret_hash=HASH, deployment_workload_digest=HASH)
    values.update(overrides)
    insert(c, "workers", **values)
    return worker


def attempt_row(c, partition, worker, *, generation=1, **overrides):
    attempt = uuid4()
    now = c.execute("SELECT clock_timestamp()").fetchone()[0]
    from datetime import timedelta
    values = dict(id=attempt, partition_id=partition, generation=generation, worker_session_id=worker,
                  claimed_at=now, lease_expires_at=now + timedelta(seconds=30),
                  hard_deadline_at=now + timedelta(seconds=600))
    values.update(overrides)
    insert(c, "attempts", **values)
    return attempt


def active_rows(c, *, count=1, **job_overrides):
    job, partitions = job_rows(c, count=count, **job_overrides)
    worker = worker_row(c)
    update(c, "jobs", ("id", job), status="RUNNING")
    update(c, "partitions", ("id", partitions[0]), status="RUNNING", generation=1, latest_generation_fk=1)
    attempt = attempt_row(c, partitions[0], worker)
    return job, partitions, worker, attempt


def artifact_row(c, partition, attempt, *, generation=1, verified=True, **overrides):
    artifact = uuid4()
    values = dict(id=artifact, attempt_id=attempt, partition_id=partition, generation=generation,
                  expected_sha256=HASH, expected_size_bytes=10, expected_schema_hash=HASH,
                  reservation_fingerprint=HASH, bucket="fixture", object_key=str(artifact))
    values.update(overrides)
    insert(c, "artifacts", **values)
    if verified:
        c.execute("UPDATE artifacts SET status='VERIFIED', object_version='opaque-v1', "
                  "verified_sha256=expected_sha256, verified_size_bytes=expected_size_bytes, "
                  "verified_schema_hash=expected_schema_hash, verified_at=clock_timestamp() WHERE id=%s", (artifact,))
    return artifact


def finish_rows(c, job, partition, attempt, artifact):
    update(c, "attempts", ("id", attempt), status="SUCCEEDED")
    update(c, "partitions", ("id", partition), status="SUCCEEDED")
    insert(c, "accepted_results", partition_id=partition, attempt_id=attempt,
           generation=1, artifact_id=artifact, publication_fingerprint=HASH)
    update(c, "jobs", ("id", job), status="SUCCEEDED")


def accepted_rows(c):
    job, partitions, worker, attempt = active_rows(c)
    artifact = artifact_row(c, partitions[0], attempt)
    finish_rows(c, job, partitions[0], attempt, artifact)
    return job, partitions[0], worker, attempt, artifact


def event_row(c, job, **overrides):
    values = dict(job_id=job, seq=1, type="FIXTURE", actor_type="test", actor_id="fixture", details={})
    values.update(overrides)
    insert(c, "events", **values)
