"""Job-locked failure/expiry disposition. Only claim creates a generation."""
from datetime import timedelta

import sqlalchemy as sa

from relay.db import schema as db
from .common import Rejection, append_event, db_time, fingerprint, one, wire
from .leases import require_live

# Workers report causes, never retry policy. Unknown codes are rejected by the API.
RETRYABLE_CODES = frozenset({"worker_crash", "store_transient", "transport_error"})
NONRETRYABLE_CODES = frozenset({"input_invalid", "schema_mismatch", "workload_validation", "integer_overflow"})


def backoff(generation):
    return min(2 ** (generation - 1), 30)


def finish_job(c, job, t, actor, *, actor_type="worker", request_id=None):
    # Every partition writer holds this job lock, so this read is authoritative.
    states = c.execute(sa.select(db.partitions.c.status).where(db.partitions.c.job_id == job["id"])).scalars().all()
    if job["status"] != "RUNNING" or any(s in ("READY", "RUNNING") for s in states):
        return
    target = "FAILED" if "FAILED" in states else "SUCCEEDED" if all(s == "SUCCEEDED" for s in states) else None
    if target is None:
        return
    c.execute(db.jobs.update().where(db.jobs.c.id == job["id"]).values(status=target, finished_at=t))
    append_event(c, job, "JOB_" + target, actor, actor_type=actor_type, occurred_at=t,
                 from_state="RUNNING", to_state=target, request_id=request_id)
    job["status"] = target


def disposition(job, attempt, code, t, retryable):
    retry = retryable and attempt["generation"] < job["max_attempts"]
    return wire(dict(job_id=job["id"], partition_id=attempt["partition_id"], attempt_id=attempt["id"],
        generation=str(attempt["generation"]), attempt_status=attempt["status"], failure_code=code,
        finished_at=t, partition_status="READY" if retry else "FAILED",
        eligible_at=t + timedelta(seconds=backoff(attempt["generation"])) if retry else None))


def settle(c, job, partition, attempt, t, status, code, retryable, actor, *, detail=None, digest=None, actor_type="worker"):
    response = disposition(job, attempt | {"status": status}, code, t, retryable)
    c.execute(db.attempts.update().where(db.attempts.c.id == attempt["id"]).values(
        status=status, finished_at=t, failure_code=code, failure_detail=detail, failure_fingerprint=digest))
    values = dict(status=response["partition_status"], last_error_code=code)
    if response["partition_status"] == "READY":
        values["eligible_at"] = t + timedelta(seconds=backoff(attempt["generation"]))
    else:
        values["finished_at"] = t
    c.execute(db.partitions.update().where(db.partitions.c.id == partition["id"]).values(**values))
    append_event(c, job, "ATTEMPT_" + status, actor, actor_type=actor_type, partition=partition["id"],
        attempt=attempt["id"], generation=attempt["generation"], occurred_at=t,
        from_state="ACTIVE", to_state=status, details={"code": code})
    append_event(c, job, "PARTITION_" + response["partition_status"], actor, actor_type=actor_type,
        partition=partition["id"], attempt=attempt["id"], generation=attempt["generation"], occurred_at=t,
        from_state="RUNNING", to_state=response["partition_status"],
        details={"code": code, "eligible_at": response["eligible_at"]})
    finish_job(c, job, t, actor, actor_type=actor_type)
    return response


def fail(engine, worker, attempt_id, model):
    if model.code not in RETRYABLE_CODES | NONRETRYABLE_CODES:
        raise Rejection("invalid_failure_code", 422)
    digest = fingerprint(model.model_dump(mode="json") | {"attempt_id": attempt_id})
    with engine.begin() as c:
        job = one(c, db.jobs, db.jobs.c.id == model.job_id, lock=True)
        partition = one(c, db.partitions, db.partitions.c.id == model.partition_id, lock=True)
        attempt = one(c, db.attempts, db.attempts.c.id == attempt_id, lock=True)
        t = db_time(c)  # AFTER the final potentially blocking authoritative lock.
        if attempt["worker_session_id"] != worker:
            raise Rejection("wrong_owner", 403)
        if partition["job_id"] != job["id"] or attempt["partition_id"] != partition["id"]:
            raise Rejection("ownership_conflict")
        if attempt["status"] == "FAILED":
            if digest != attempt["failure_fingerprint"]:
                raise Rejection("idempotency_conflict")
            # Reconstruct the recorded disposition from immutable terminal fields
            # and immutable policy, not the partition's possibly newer state.
            return disposition(job, attempt, attempt["failure_code"], attempt["finished_at"],
                               attempt["failure_code"] in RETRYABLE_CODES)
        if t >= attempt["lease_expires_at"] or t >= attempt["hard_deadline_at"]:
            raise Rejection("lease_expired")
        require_live(job, partition, attempt, worker, int(model.generation), t)
        response = settle(c, job, partition, attempt, t, "FAILED", model.code,
                          model.code in RETRYABLE_CODES, worker, detail=model.detail, digest=digest)
    return response
