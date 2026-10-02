import hashlib
import json
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa

from relay.db import schema as db


class Rejection(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status


def wire(value):
    if isinstance(value, (UUID, datetime)): return value.isoformat() if isinstance(value, datetime) else str(value)
    if isinstance(value, dict): return {k: wire(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [wire(v) for v in value]
    return value


def canonical(value):
    return json.dumps(wire(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def one(c, table, predicate, *, lock=False):
    statement = sa.select(table).where(predicate)
    if lock: statement = statement.with_for_update()
    row = c.execute(statement).mappings().first()
    if row is None: raise Rejection("not_found", 404)
    return dict(row)


def db_time(c):
    return c.scalar(sa.select(sa.func.clock_timestamp()))


def receipt(c, scope, key, request_hash):
    row = c.execute(sa.select(db.request_receipts).where(
        db.request_receipts.c.scope == scope, db.request_receipts.c.key == key)).mappings().first()
    if row:
        if row["request_hash"] != request_hash: raise Rejection("idempotency_conflict")
        return dict(row)


def save_receipt(c, scope, key, request_hash, operation, status, response, **identities):
    c.execute(db.request_receipts.insert().values(scope=scope, key=key, request_hash=request_hash,
              operation=operation, status_code=status, response=wire(response), **identities))


def append_event(c, job, event_type, actor_id, *, partition=None, attempt=None, generation=None,
                 from_state=None, to_state=None, occurred_at=None, details=None, request_id=None, actor_type=None):
    values = dict(job_id=job["id"], seq=job["next_event_seq"], type=event_type,
        actor_type=actor_type or ("operator" if event_type == "JOB_SUBMITTED" else "worker"), actor_id=str(actor_id),
        from_state=from_state, to_state=to_state, details=details or {}, request_id=request_id)
    if occurred_at is not None: values["occurred_at"] = occurred_at
    if partition is not None: values["partition_id"] = partition
    if attempt is not None:
        values.update(attempt_id=attempt, attempt_partition_id=partition, attempt_generation=generation)
    c.execute(db.events.insert().values(**values))
    job["next_event_seq"] += 1
    c.execute(db.jobs.update().where(db.jobs.c.id == job["id"]).values(next_event_seq=job["next_event_seq"]))
