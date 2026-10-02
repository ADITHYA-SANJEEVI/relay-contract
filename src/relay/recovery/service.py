"""Unlocked discovery; one canonical, post-lock recheck per transaction."""
import logging
import json

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from relay.db import schema as db
from relay.control.common import db_time, one, wire
from relay.control.settlement import settle

logger = logging.getLogger("relay.recovery")


def discover(engine, batch=100):
    # The scalar subquery is an initplan time bound for the existing expiry index.
    # It is discovery information only and is never used as settlement time.
    with engine.connect() as c:
        return [dict(row) for row in c.execute(sa.select(db.attempts.c.id.label("attempt_id"),
            db.attempts.c.partition_id, db.partitions.c.job_id, db.attempts.c.generation)
            .join(db.partitions, db.partitions.c.id == db.attempts.c.partition_id)
            .where(db.attempts.c.status == "ACTIVE",
                db.attempts.c.lease_expires_at <= sa.select(sa.func.clock_timestamp()).scalar_subquery())
            .order_by(db.attempts.c.lease_expires_at, db.attempts.c.partition_id).limit(batch)).mappings()]


def expire(engine, candidate):
    with engine.begin() as c:
        job = one(c, db.jobs, db.jobs.c.id == candidate["job_id"], lock=True)
        partition = one(c, db.partitions, db.partitions.c.id == candidate["partition_id"], lock=True)
        attempt = one(c, db.attempts, db.attempts.c.id == candidate["attempt_id"], lock=True)
        t = db_time(c)
        response = wire(candidate | {"generation": str(candidate["generation"]), "operation": "recovery", "db_time": t, "outcome": "noop"})
        current = (job["status"] == "RUNNING" and partition["status"] == "RUNNING"
            and partition["job_id"] == job["id"] and attempt["partition_id"] == partition["id"]
            and partition["generation"] == partition["latest_generation_fk"] == attempt["generation"]
            and attempt["generation"] == candidate["generation"] and attempt["status"] == "ACTIVE")
        if not current:
            return response | {"reason": "already_settled_or_superseded"}
        if t < attempt["lease_expires_at"] and t < attempt["hard_deadline_at"]:
            return response | {"reason": "still_live"}
        code = "hard_deadline_exceeded" if t >= attempt["hard_deadline_at"] else "lease_expired"
        response = settle(c, job, partition, attempt, t, "EXPIRED", code, True, "recovery", actor_type="recovery")
    return response | {"operation": "recovery", "db_time": t, "outcome": "expired", "reason": code}


def run_batch(engine, batch=100):
    results = []
    for candidate in discover(engine, batch):
        try:
            result = expire(engine, candidate)
        except SQLAlchemyError:
            # A commit disconnect can be uncertain. Rescan durable state next poll;
            # never infer rollback or schedule work from a process-local decision.
            result = wire(candidate | {"generation": str(candidate["generation"]), "operation": "recovery", "outcome": "unknown", "reason": "database_unavailable"})
        logger.info(json.dumps(wire(result), sort_keys=True))
        results.append(result)
    return results
