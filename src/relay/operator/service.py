"""Bounded PostgreSQL snapshots. This module contains no state-changing SQL."""

import base64
import binascii
import json
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from uuid import UUID

import sqlalchemy as sa
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from relay.control.common import Rejection
from relay.db import schema as db
from relay.workloads.reference import OUTPUT_SCHEMA, WorkloadError, read_parquet

from . import models as m

SCHEMA_REVISION = "0003_operator_indexes"
MAX_BIGINT = 9223372036854775807


def columns(table, prefix, names=None):
    return [table.c[name].label(prefix + name) for name in (names or table.c.keys())]


def projected(row, prefix):
    return {key[len(prefix):]: value for key, value in row.items() if key.startswith(prefix)}


def counter(value):
    return None if value is None else str(value)


def authority(row):
    # No dependence on partition/latest attempt state, generation or object storage.
    if row is None or row.get("partition_id") is None:
        return m.NoAuthority()
    return m.AcceptedAuthority(result=m.AcceptedResult(**{
        key: counter(row[key]) if key == "generation" else row[key]
        for key in m.AcceptedResult.model_fields}))


def artifact(row):
    if row is None or row.get("id") is None:
        return None
    return m.ArtifactMetadata(**{
        key: counter(row[key]) if key in ("generation", "expected_size_bytes", "verified_size_bytes") else row[key]
        for key in m.ArtifactMetadata.model_fields if key != "content_verification"})


def sequence(value):
    if not re.fullmatch(r"0|[1-9][0-9]{0,18}", value) or int(value) > MAX_BIGINT:
        raise Rejection("invalid_cursor", 422)
    return int(value)


def read_contract(model):
    def decorate(method):
        @wraps(method)
        def read(self, *args, **kwargs):
            with self.snapshot() as (c, t):
                try:
                    return model(as_of=t, **method(self, c, t, *args, **kwargs))
                except ValidationError as error:
                    raise Rejection("malformed_persisted_diagnostic", 503) from error
        return read
    return decorate


def get_row(c, statement):
    row = c.execute(statement).mappings().first()
    if row is None:
        raise Rejection("not_found", 404)
    return row


def job_query():
    j, p, a, r = db.jobs, db.partitions, db.attempts, db.accepted_results
    names = ("id", "definition_hash", "workload_name", "workload_version", "status", "created_at",
             "started_at", "finished_at", "partition_count", "next_event_seq")
    return sa.select(*[j.c[name] for name in names],
        sa.select(sa.func.count()).select_from(a.join(p, p.c.id == a.c.partition_id))
        .where(p.c.job_id == j.c.id).correlate(j).scalar_subquery().label("attempt_count"),
        sa.select(sa.func.count()).select_from(r.join(p, p.c.id == r.c.partition_id))
        .where(p.c.job_id == j.c.id).correlate(j).scalar_subquery().label("partial_result_count"),
        *[sa.select(sa.func.count()).where(p.c.job_id == j.c.id, p.c.status == state)
          .correlate(j).scalar_subquery().label("count_" + state) for state in m.PartitionCounts.model_fields])


def job_model(row):
    return m.JobSummary(**{key: counter(row[key]) if key in
        ("partition_count", "attempt_count", "next_event_seq", "partial_result_count") else row[key]
        for key in m.JobSummary.model_fields if key not in ("partition_counts", "complete")},
        partition_counts={state: str(row["count_" + state]) for state in m.PartitionCounts.model_fields},
        complete=row["status"] == "SUCCEEDED")


def attempt_query():
    a, p, f, r = db.attempts, db.partitions, db.artifacts, db.accepted_results
    safe = ("id", "partition_id", "generation", "worker_session_id", "status", "claimed_at",
            "lease_expires_at", "hard_deadline_at", "last_renew_seq", "finished_at", "failure_code")
    return sa.select(*columns(a, "a_", safe), *columns(f, "f_"), *columns(r, "r_"),
        p.c.job_id, p.c.ordinal, p.c.generation.label("current_generation")).select_from(
            a.join(p, p.c.id == a.c.partition_id).outerjoin(f, f.c.attempt_id == a.c.id)
            .outerjoin(r, r.c.partition_id == p.c.id))


def attempt_model(row, t):
    a = projected(row, "a_")
    accepted = authority(projected(row, "r_"))
    if a["status"] != "ACTIVE":
        observed = "TERMINAL"
    elif a["generation"] != row["current_generation"]:
        observed = "SUPERSEDED"
    elif t >= min(a["lease_expires_at"], a["hard_deadline_at"]):
        observed = "DEADLINE_PASSED"
    else:
        observed = "WITHIN_DEADLINES"
    return m.AttemptObservation(**{key: counter(value) if key in ("generation", "last_renew_seq") else value
        for key, value in a.items()}, job_id=row["job_id"], ordinal=row["ordinal"],
        current_generation=str(row["current_generation"]), ownership_observation=observed,
        artifact=artifact(projected(row, "f_")), accepted_authority=accepted,
        is_accepted_attempt=isinstance(accepted, m.AcceptedAuthority) and accepted.result.attempt_id == a["id"],
        events_url=f"/v1/operator/jobs/{row['job_id']}/events?attempt_id={a['id']}")


def partition_model(row, latest, accepted):
    return m.PartitionObservation(**{key: counter(row[key]) if key == "generation" else row[key]
        for key in m.PartitionObservation.model_fields if key not in ("latest_attempt", "accepted_authority")},
        latest_attempt=latest, accepted_authority=accepted)


def safe_details_expression(table):
    # Avoid transferring/decoding arbitrary oversized JSONB into the API process.
    text = sa.cast(table.c.details, sa.Text)
    return sa.case((sa.func.octet_length(text) <= 4096, text),
                   else_=None).label("details")


DETAIL_FIELDS = {
    "LEASE_RENEWED": {"sequence": "sequence", "lease_expires_at": "time"},
    "ARTIFACT_RESERVED": {"artifact_id": "uuid"},
    "RESULT_ACCEPTED": {"artifact_id": "uuid"},
    "PUBLICATION_REJECTED": {"code": "code"},
    "ATTEMPT_FAILED": {"code": "code"},
    "ATTEMPT_EXPIRED": {"code": "code"},
    "PARTITION_READY": {"code": "code", "eligible_at": "time"},
    "PARTITION_FAILED": {"code": "code", "eligible_at": "time"},
    "WORKER_DRAINING": {"from_state": "worker_state", "to_state": "worker_state"},
    "WORKER_STOPPED": {"from_state": "worker_state", "to_state": "worker_state"},
}

DIAGNOSTIC_CODES = frozenset(("worker_crash", "store_transient", "transport_error", "input_invalid",
    "schema_mismatch", "workload_validation", "integer_overflow", "lease_expired", "hard_deadline_exceeded",
    "not_found", "wrong_owner", "result_conflict", "stale_generation", "artifact_identity_mismatch",
    "artifact_not_verified", "job_cancelled", "terminal_job", "attempt_terminal"))


def diagnostic_details(event_type, value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            value = None
    if not isinstance(value, dict):
        return m.DiagnosticDetails(state="MALFORMED", values={}, omitted=True)
    allowed = DETAIL_FIELDS.get(event_type, {})
    safe, malformed = {}, False
    for key, kind in allowed.items():
        if key not in value:
            continue
        field = value[key]
        try:
            if field is None and key == "eligible_at":
                safe[key] = None
                continue
            if not isinstance(field, str) or len(field) > 128:
                raise ValueError()
            if kind == "uuid":
                UUID(field)
            elif kind == "sequence":
                sequence(field)
            elif kind == "time":
                parsed = datetime.fromisoformat(field)
                if parsed.tzinfo is None:
                    raise ValueError()
            elif kind == "worker_state" and field not in ("REGISTERED", "DRAINING", "STOPPED"):
                raise ValueError()
            elif kind == "code" and field not in DIAGNOSTIC_CODES:
                raise ValueError()
            safe[key] = field
        except (ValueError, Rejection):
            malformed = True
    return m.DiagnosticDetails(state="MALFORMED" if malformed else "SANITIZED", values=safe,
                               omitted=set(value) != set(safe))


def event_columns(table, names):
    # These are recorded strings, not arbitrary request/failure payloads. Reject
    # malformed oversized outer fields rather than silently truncating identities.
    return [table.c[name] for name in names] + [safe_details_expression(table)]


def event_model(row, model):
    values = dict(row)
    for key, value in values.items():
        if key != "details" and isinstance(value, str) and len(value) > 128:
            raise Rejection("malformed_persisted_diagnostic", 503)
    values["seq"] = str(values["seq"])
    if "attempt_generation" in values:
        values["attempt_generation"] = counter(values["attempt_generation"])
    values["details"] = diagnostic_details(values["type"], values["details"])
    return model(**values)


class OperatorReads:
    def __init__(self, engine, gateway):
        self.engine, self.gateway = engine, gateway

    @contextmanager
    def snapshot(self):
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            with c.begin():
                c.execute(sa.text("SET TRANSACTION READ ONLY"))
                # First SELECT acquires the MVCC snapshot and samples its observation clock.
                yield c, c.scalar(sa.select(sa.func.clock_timestamp()))

    @read_contract(m.JobPage)
    def jobs(self, c, t, cursor, limit, status):
        j = db.jobs
        statement = job_query()
        if status:
            statement = statement.where(j.c.status == status)
        if cursor:
            try:
                if len(cursor) > 512:
                    raise ValueError()
                data = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
                if not isinstance(data, list) or len(data) != 3 or data[2] != status:
                    raise ValueError()
                created, identity = datetime.fromisoformat(data[0]), UUID(data[1])
                if created.tzinfo is None:
                    raise ValueError()
            except (ValueError, TypeError, binascii.Error):
                raise Rejection("invalid_cursor", 422)
            statement = statement.where(sa.tuple_(j.c.created_at, j.c.id) < sa.tuple_(created, identity))
        rows = c.execute(statement.order_by(j.c.created_at.desc(), j.c.id.desc()).limit(limit + 1)).mappings().all()
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = base64.urlsafe_b64encode(json.dumps(
                [last["created_at"].isoformat(), str(last["id"]), status], separators=(",", ":")).encode()).decode()
        return dict(items=[job_model(row) for row in rows[:limit]], next_cursor=next_cursor)

    @read_contract(m.JobSnapshot)
    def job(self, c, t, identity):
        return dict(job=job_model(get_row(c, job_query().where(db.jobs.c.id == identity))))

    @read_contract(m.PartitionPage)
    def partitions(self, c, t, identity, after_ordinal, limit, status):
        get_row(c, sa.select(db.jobs.c.id).where(db.jobs.c.id == identity))
        p = db.partitions
        statement = sa.select(p).where(p.c.job_id == identity, p.c.ordinal > after_ordinal)
        if status:
            statement = statement.where(p.c.status == status)
        rows = c.execute(statement.order_by(p.c.ordinal).limit(limit + 1)).mappings().all()
        page = rows[:limit]
        ids = [row["id"] for row in page]
        current = c.execute(attempt_query().where(db.attempts.c.partition_id.in_(ids),
            db.attempts.c.generation == db.partitions.c.latest_generation_fk)).mappings().all()
        latest = {row["a_partition_id"]: attempt_model(row, t) for row in current}
        accepted = {row["partition_id"]: authority(row) for row in c.execute(
            sa.select(db.accepted_results).where(db.accepted_results.c.partition_id.in_(ids))).mappings()}
        return dict(job_id=identity, items=[partition_model(row, latest.get(row["id"]),
            accepted.get(row["id"], m.NoAuthority())) for row in page],
            next_cursor=page[-1]["ordinal"] if len(rows) > limit else None)

    @read_contract(m.PartitionSnapshot)
    def partition(self, c, t, identity):
        p = get_row(c, sa.select(db.partitions).where(db.partitions.c.id == identity))
        history = c.execute(attempt_query().where(db.attempts.c.partition_id == identity)
            .order_by(db.attempts.c.generation.desc(), db.attempts.c.id).limit(11)).mappings().all()
        if len(history) > 10:
            raise Rejection("malformed_persisted_diagnostic", 503)
        attempts = [attempt_model(row, t) for row in history]
        latest = next((a for a in attempts if int(a.generation) == p["latest_generation_fk"]), None)
        accepted = c.execute(sa.select(db.accepted_results).where(
            db.accepted_results.c.partition_id == identity)).mappings().first()
        return dict(partition=partition_model(p, latest, authority(accepted)), attempts=attempts)

    @read_contract(m.AttemptSnapshot)
    def attempt(self, c, t, identity):
        row = get_row(c, attempt_query().where(db.attempts.c.id == identity))
        return dict(attempt=attempt_model(row, t))

    @read_contract(m.ArtifactSnapshot)
    def artifact(self, c, t, identity):
        row = get_row(c, attempt_query().where(db.artifacts.c.id == identity))
        accepted = authority(projected(row, "r_"))
        return dict(job_id=row["job_id"], ordinal=row["ordinal"], artifact=artifact(projected(row, "f_")),
            accepted_authority=accepted, is_accepted_artifact=isinstance(accepted, m.AcceptedAuthority)
            and accepted.result.artifact_id == identity)

    @read_contract(m.ResultPage)
    def results(self, c, t, identity, after_ordinal, limit):
        job = job_model(get_row(c, job_query().where(db.jobs.c.id == identity)))
        rows = c.execute(attempt_query().where(db.partitions.c.job_id == identity,
            db.partitions.c.ordinal > after_ordinal, db.accepted_results.c.attempt_id == db.attempts.c.id)
            .order_by(db.partitions.c.ordinal).limit(limit + 1)).mappings().all()
        items = [m.ResultManifest(ordinal=row["ordinal"], authority=authority(projected(row, "r_")),
            artifact=artifact(projected(row, "f_")),
            content_url=f"/v1/artifacts/{row['r_artifact_id']}/content",
            verification_url=f"/v1/operator/artifacts/{row['r_artifact_id']}/verification") for row in rows[:limit]]
        return dict(job_id=identity, job_status=job.status, complete=job.complete, partition_count=job.partition_count,
            partial_result_count=job.partial_result_count, items=items,
            next_cursor=rows[limit - 1]["ordinal"] if len(rows) > limit else None)

    @read_contract(m.EventPage)
    def events(self, c, t, identity, after_seq, before_seq, direction, limit, partition_id, attempt_id):
        job = get_row(c, sa.select(db.jobs.c.next_event_seq).where(db.jobs.c.id == identity))
        if partition_id:
            get_row(c, sa.select(db.partitions.c.id).where(db.partitions.c.id == partition_id,
                db.partitions.c.job_id == identity))
        if attempt_id:
            get_row(c, sa.select(db.attempts.c.id).select_from(db.attempts.join(db.partitions,
                db.partitions.c.id == db.attempts.c.partition_id)).where(db.attempts.c.id == attempt_id,
                db.partitions.c.job_id == identity, *([db.partitions.c.id == partition_id] if partition_id else [])))
        if (direction == "forward" and before_seq is not None) or (direction == "backward" and after_seq is not None):
            raise Rejection("invalid_range", 422)
        e = db.events
        names = tuple(key for key in m.EventObservation.model_fields if key != "details")
        statement = sa.select(*event_columns(e, names)).where(e.c.job_id == identity)
        if partition_id:
            statement = statement.where(e.c.partition_id == partition_id)
        if attempt_id:
            statement = statement.where(e.c.attempt_id == attempt_id)
        if direction == "forward":
            statement = statement.where(e.c.seq > sequence(after_seq or "0")).order_by(e.c.seq)
        else:
            upper = sequence(before_seq) if before_seq is not None else job["next_event_seq"]
            statement = statement.where(e.c.seq < upper).order_by(e.c.seq.desc())
        rows = c.execute(statement.limit(limit + 1)).mappings().all()
        page = rows[:limit]
        next_cursor = str(page[-1]["seq"]) if len(rows) > limit else None
        if direction == "backward":
            page = list(reversed(page))  # Every delivered page remains chronological.
        return dict(job_id=identity, direction=direction, partition_id=partition_id, attempt_id=attempt_id,
            items=[event_model(row, m.EventObservation) for row in page],
            loaded_from_seq=str(page[0]["seq"]) if page else None,
            loaded_through_seq=str(page[-1]["seq"]) if page else None,
            frontier_seq=str(job["next_event_seq"] - 1), has_more=len(rows) > limit, next_cursor=next_cursor)

    def worker_models(self, c, t, rows):
        assignments = c.execute(attempt_query().where(db.attempts.c.worker_session_id.in_(
            [row["session_id"] for row in rows]), db.attempts.c.status == "ACTIVE")).mappings().all()
        current = {row["a_worker_session_id"]: attempt_model(row, t) for row in assignments}
        return [m.WorkerObservation(**{key: counter(row[key]) if key == "last_heartbeat_seq" else row[key]
            for key in m.WorkerObservation.model_fields if key not in ("liveness", "current_attempt")},
            liveness="NOT_APPLICABLE" if row["state"] == "STOPPED" else
                "FRESH" if t - row["last_seen_at"] < timedelta(seconds=30) else "SUSPECT",
            current_attempt=current.get(row["session_id"])) for row in rows]

    @staticmethod
    def worker_query():
        return sa.select(*[db.workers.c[key] for key in m.WorkerObservation.model_fields
                           if key not in ("liveness", "current_attempt")])

    @read_contract(m.WorkerPage)
    def workers(self, c, t, after_session, limit, state):
        w = db.workers
        statement = self.worker_query()
        if after_session:
            statement = statement.where(w.c.session_id > after_session)
        if state:
            statement = statement.where(w.c.state == state)
        rows = c.execute(statement.order_by(w.c.session_id).limit(limit + 1)).mappings().all()
        return dict(items=self.worker_models(c, t, rows[:limit]),
            next_cursor=rows[limit - 1]["session_id"] if len(rows) > limit else None)

    @read_contract(m.WorkerSnapshot)
    def worker(self, c, t, identity):
        row = get_row(c, self.worker_query().where(db.workers.c.session_id == identity))
        return dict(worker=self.worker_models(c, t, [row])[0])

    @read_contract(m.ParticipationPage)
    def participation(self, c, t, identity, after_attempt, limit):
        get_row(c, sa.select(db.workers.c.session_id).where(db.workers.c.session_id == identity))
        statement = attempt_query().where(db.attempts.c.worker_session_id == identity)
        if after_attempt:
            statement = statement.where(db.attempts.c.id > after_attempt)
        rows = c.execute(statement.order_by(db.attempts.c.id).limit(limit + 1)).mappings().all()
        return dict(session_id=identity, items=[attempt_model(row, t) for row in rows[:limit]],
            next_cursor=rows[limit - 1]["a_id"] if len(rows) > limit else None)

    @read_contract(m.WorkerEventPage)
    def worker_events(self, c, t, identity, after_seq, limit):
        w = get_row(c, sa.select(db.workers.c.next_event_seq).where(db.workers.c.session_id == identity))
        e = db.worker_events
        names = tuple(key for key in m.WorkerEvent.model_fields if key != "details")
        rows = c.execute(sa.select(*event_columns(e, names)).where(e.c.session_id == identity,
            e.c.seq > sequence(after_seq)).order_by(e.c.seq).limit(limit + 1)).mappings().all()
        page = rows[:limit]
        return dict(session_id=identity, items=[event_model(row, m.WorkerEvent) for row in page],
            loaded_from_seq=str(page[0]["seq"]) if page else None,
            loaded_through_seq=str(page[-1]["seq"]) if page else None,
            frontier_seq=str(w["next_event_seq"] - 1), has_more=len(rows) > limit,
            next_cursor=str(page[-1]["seq"]) if len(rows) > limit else None)

    @read_contract(m.DefinitionSnapshot)
    def definition(self, c, t, identity):
        j = get_row(c, sa.select(db.jobs).where(db.jobs.c.id == identity))
        i, f, p, s = db.job_inputs, db.input_artifacts, db.partitions, db.partition_inputs
        inputs = c.execute(sa.select(i.c.input_ordinal, i.c.input_artifact_id.label("artifact_id"),
            f.c.object_version, f.c.sha256, f.c.size_bytes, f.c.schema_hash, f.c.row_count)
            .select_from(i.join(f, f.c.id == i.c.input_artifact_id)).where(i.c.job_id == identity)
            .order_by(i.c.input_ordinal).limit(4097)).mappings().all()
        parts = c.execute(sa.select(p.c.id, p.c.ordinal).where(p.c.job_id == identity)
            .order_by(p.c.ordinal).limit(4097)).mappings().all()
        slices = c.execute(sa.select(s.c.partition_id, s.c.slice_ordinal, s.c.input_ordinal,
            s.c.first_row, s.c.row_count).join(p, p.c.id == s.c.partition_id).where(p.c.job_id == identity)
            .order_by(p.c.ordinal, s.c.slice_ordinal).limit(65537)).mappings().all()
        if len(inputs) > 4096 or len(parts) > 4096 or len(slices) > 65536:
            raise Rejection("malformed_persisted_diagnostic", 503)
        by_part = {row["id"]: [] for row in parts}
        for row in slices:
            by_part[row["partition_id"]].append(m.InputSlice(**{key: counter(row[key]) if key in
                ("first_row", "row_count") else row[key] for key in m.InputSlice.model_fields}))
        return dict(job_id=identity, version=j["version"], parent_job_id=j["parent_job_id"],
            definition_hash=j["definition_hash"], manifest_hash=j["manifest_hash"],
            workload=dict(name=j["workload_name"], version=j["workload_version"], digest=j["workload_digest"]),
            parameters=j["parameters"], policy={key: j[key] for key in ("max_attempts", "lease_seconds", "max_attempt_seconds")},
            inputs=[m.InputMetadata(**{key: counter(value) if key in ("size_bytes", "row_count") else value
                for key, value in row.items()}) for row in inputs],
            partitions=[m.DefinitionPartition(partition_id=row["id"], ordinal=row["ordinal"],
                slices=by_part[row["id"]]) for row in parts])

    def verification(self, identity):
        # Metadata transaction has closed before any object-store I/O.
        metadata = self.artifact(identity)
        if not metadata.is_accepted_artifact:
            raise Rejection("accepted_content_unavailable", 409)
        row = metadata.artifact.model_dump()
        code = "verified"
        try:
            with self.gateway.read_exact(row, row["object_version"], row["verified_sha256"], int(row["verified_size_bytes"])) as stored:
                read_parquet(stored, OUTPUT_SCHEMA)
        except ClientError as error:
            store_code = error.response.get("Error", {}).get("Code")
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = "version_unavailable" if store_code == "NoSuchVersion" else \
                "storage_missing" if store_code in ("NoSuchKey", "NoSuchBucket") else \
                "storage_unavailable" if status is not None and status >= 500 else "transport_read_failure"
        except BotoCoreError:
            code = "storage_unavailable"
        except Rejection as error:
            code = {"stored_integrity_mismatch": "checksum_mismatch", "stored_size_mismatch": "size_mismatch",
                "object_version_mismatch": "version_unavailable", "missing_object_version": "version_unavailable"}.get(
                error.code, "content_invalid")
        except WorkloadError:
            code = "content_invalid"
        except (OSError, ValueError):
            code = "transport_read_failure"
        return m.VerificationSnapshot(**metadata.model_dump(), verification=m.VerificationResult(
            state="VERIFIED" if code == "verified" else "FAILED", code=code,
            checked_at=datetime.now(timezone.utc), object_version=row["object_version"],
            sha256=row["verified_sha256"], size_bytes=row["verified_size_bytes"]))

    @read_contract(m.Capabilities)
    def capabilities(self, c, t):
        revision = c.scalar(sa.text("SELECT version_num FROM relay_schema_version"))
        return dict(database_revision=revision, capabilities=[m.CapabilityState(id=identifier,
            state=state, routes=routes, reason=reason) for identifier, state, routes, reason in CAPABILITIES])


CAPABILITIES = (
    ("BV01_JOBS_CATALOGUE", "AVAILABLE", ("GET /v1/operator/jobs", "GET /v1/operator/jobs/{id}"), None),
    ("BV02_SUMMARY", "DEFERRED", (), "Installation aggregates are outside the minimum investigation surface."),
    ("BV03_PARTITION_HISTORY", "AVAILABLE", ("GET /v1/operator/jobs/{id}/partitions",
        "GET /v1/operator/partitions/{id}", "GET /v1/operator/partitions/{id}/history"), None),
    ("BV04_ATTEMPT_DETAIL", "AVAILABLE", ("GET /v1/operator/attempts/{id}",), None),
    ("BV05_ARTIFACT_METADATA", "AVAILABLE", ("GET /v1/operator/artifacts/{id}",
        "GET /v1/operator/artifacts/{id}/verification"), None),
    ("BV06_RESULT_METADATA", "AVAILABLE", ("GET /v1/operator/jobs/{id}/result-metadata",), None),
    ("BV07_FLEET_HISTORY", "AVAILABLE", ("GET /v1/operator/workers", "GET /v1/operator/workers/{id}",
        "GET /v1/operator/workers/{id}/attempts", "GET /v1/operator/workers/{id}/events"), None),
    ("BV08_TAIL_FILTER_EVENTS", "AVAILABLE", ("GET /v1/operator/jobs/{id}/events",), None),
    ("BV09_DEFINITION", "AVAILABLE", ("GET /v1/operator/jobs/{id}/definition",), None),
    ("BV10_BROWSER_AUTH", "DEFERRED", (), "Existing local operator bearer only; no browser session adapter."),
    ("BV11_REPORTS_CONTROLLER", "DEFERRED", (), "Reports and isolated fault controller require separate contracts."),
    ("BV12_OBSERVATION_CLOCK", "AVAILABLE", ("GET /v1/operator/capabilities",), None),
)
