"""Session telemetry and live ownership renewal, without expiry settlement."""

from datetime import timedelta

import sqlalchemy as sa

from relay.db import schema as db
from .common import Rejection, append_event, db_time, fingerprint, one, wire


def heartbeat(engine, session, sequence):
    with engine.begin() as c:
        worker = one(c, db.workers, db.workers.c.session_id == session, lock=True)
        t = db_time(c)
        applied = int(sequence) > worker["last_heartbeat_seq"]
        if applied:
            c.execute(db.workers.update().where(db.workers.c.session_id == session).values(
                last_heartbeat_seq=int(sequence), last_seen_at=t))
            worker.update(last_heartbeat_seq=int(sequence), last_seen_at=t)
        response = wire(dict(session_id=session, state=worker["state"], db_time=t,
            last_heartbeat_seq=str(worker["last_heartbeat_seq"]), last_seen_at=worker["last_seen_at"],
            liveness="FRESH" if t - worker["last_seen_at"] < timedelta(seconds=30) else "SUSPECT",
            applied=applied))
    return response


def lifecycle(engine, session, target):
    # Claim also holds this worker row while checking state/creating ACTIVE work.
    # No job/partition locks are acquired here, so no reverse lock dependency.
    with engine.begin() as c:
        worker = one(c, db.workers, db.workers.c.session_id == session, lock=True)
        if worker["state"] == "STOPPED" or worker["state"] == target:
            return wire(dict(session_id=session, state=worker["state"], stopped_at=worker["stopped_at"]))
        if target == "STOPPED" and c.scalar(sa.select(sa.exists().where(
            db.attempts.c.worker_session_id == session, db.attempts.c.status == "ACTIVE"))):
            raise Rejection("worker_busy")
        t = db_time(c)
        stopped = t if target == "STOPPED" else None
        c.execute(db.workers.update().where(db.workers.c.session_id == session).values(
            state=target, stopped_at=stopped, next_event_seq=worker["next_event_seq"] + 1))
        c.execute(db.worker_events.insert().values(session_id=session, seq=worker["next_event_seq"],
            type="WORKER_" + target, occurred_at=t, details={"from_state": worker["state"], "to_state": target}))
        response = wire(dict(session_id=session, state=target, stopped_at=stopped))
    return response


def require_live(job, partition, attempt, worker, generation, t):
    if attempt["worker_session_id"] != worker:
        raise Rejection("wrong_owner", 403)
    if (partition["job_id"] != job["id"] or attempt["partition_id"] != partition["id"]
        or partition["generation"] != generation or partition["latest_generation_fk"] != generation
        or attempt["generation"] != generation):
        raise Rejection("stale_generation")
    if job["status"] != "RUNNING":
        raise Rejection("terminal_job")
    if attempt["status"] != "ACTIVE" or partition["status"] != "RUNNING":
        raise Rejection("attempt_terminal")
    if t >= attempt["lease_expires_at"] or t >= attempt["hard_deadline_at"]:
        raise Rejection("lease_expired")


def renew(engine, worker, attempt_id, model):
    digest = fingerprint(model.model_dump(mode="json") | {"attempt_id": attempt_id})
    sequence = int(model.sequence)
    with engine.begin() as c:
        job = one(c, db.jobs, db.jobs.c.id == model.job_id, lock=True)
        partition = one(c, db.partitions, db.partitions.c.id == model.partition_id, lock=True)
        attempt = one(c, db.attempts, db.attempts.c.id == attempt_id, lock=True)
        t = db_time(c)  # One fresh sample AFTER job -> partition -> attempt.
        if attempt["worker_session_id"] != worker:
            raise Rejection("wrong_owner", 403)
        if t >= attempt["lease_expires_at"] or t >= attempt["hard_deadline_at"]:
            raise Rejection("lease_expired")
        # A conflicting repeat only rejects; never grants authority on changed IDs.
        if (sequence == attempt["last_renew_seq"] and attempt["last_renew_fingerprint"] is not None
            and digest != attempt["last_renew_fingerprint"]):
            raise Rejection("idempotency_conflict")
        require_live(job, partition, attempt, worker, int(model.generation), t)
        if sequence == attempt["last_renew_seq"] and attempt["last_renew_response"] is not None:
            return attempt["last_renew_response"], "ignored"
        if sequence <= attempt["last_renew_seq"]:
            return wire(dict(applied=False, sequence=str(attempt["last_renew_seq"]),
                lease_expires_at=attempt["lease_expires_at"], hard_deadline_at=attempt["hard_deadline_at"], db_time=t)), "ignored"
        lease = min(t + timedelta(seconds=job["lease_seconds"]), attempt["hard_deadline_at"])
        response = wire(dict(applied=True, sequence=str(sequence), lease_expires_at=lease,
            hard_deadline_at=attempt["hard_deadline_at"], db_time=t))
        c.execute(db.attempts.update().where(db.attempts.c.id == attempt_id).values(
            lease_expires_at=lease, last_renew_seq=sequence, last_renew_fingerprint=digest, last_renew_response=response))
        append_event(c, job, "LEASE_RENEWED", worker, partition=partition["id"], attempt=attempt_id,
            generation=attempt["generation"], occurred_at=t,
            details={"sequence": str(sequence), "lease_expires_at": response["lease_expires_at"]})
    return response, "applied"
