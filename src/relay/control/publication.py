"""Fenced publication using immutable VERIFIED metadata; no object-store I/O."""

from urllib.parse import quote

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from relay.db import schema as db

from .common import append_event, db_time, fingerprint, receipt, save_receipt, wire
from .settlement import finish_job


def artifact_uri(artifact):
    """Registered bucket/key plus opaque version; caller URLs are never fetched."""
    return (f"s3://{artifact['bucket']}/{quote(artifact['object_key'], safe='/')}"
            f"?versionId={quote(artifact['object_version'], safe='')}")


def accepted_response(result, artifact):
    return wire({k: result[k] for k in ("partition_id", "attempt_id", "artifact_id", "accepted_at")} | {
        "generation": str(result["generation"]), "sha256": artifact["verified_sha256"],
        "artifact_uri": artifact_uri(artifact), "object_version": artifact["object_version"],
        "size_bytes": str(artifact["verified_size_bytes"])})


def optional(c, table, predicate, *, lock=False):
    statement = sa.select(table).where(predicate)
    if lock:
        statement = statement.with_for_update()
    row = c.execute(statement).mappings().first()
    return dict(row) if row is not None else None


def publication_fingerprint(model, attempt_id, artifact):
    return fingerprint({"job_id": model.job_id, "partition_id": model.partition_id,
        "attempt_id": attempt_id, "generation": model.generation, "artifact_id": model.artifact_id,
        "bucket": artifact["bucket"], "object_key": artifact["object_key"],
        "object_version": artifact["object_version"], "size_bytes": str(artifact["verified_size_bytes"]),
        "sha256": model.sha256, "artifact_uri": model.artifact_uri})


# Every identity and live condition is tested by the database mutation itself.
# t is bound once after all row locks; rowcount (not a Python check) gates insertion.
FENCED_UPDATE = sa.text("""
UPDATE partitions AS p SET status='SUCCEEDED', finished_at=:t
FROM jobs AS j, attempts AS a, artifacts AS f
WHERE p.id=:partition_id AND p.job_id=:job_id AND j.id=p.job_id
  AND j.status='RUNNING' AND p.status='RUNNING'
  AND p.generation=:generation AND p.latest_generation_fk=:generation
  AND a.id=:attempt_id AND a.partition_id=p.id AND a.generation=:generation
  AND a.worker_session_id=:worker AND a.status='ACTIVE'
  AND :t < a.lease_expires_at AND :t < a.hard_deadline_at
  AND f.id=:artifact_id AND f.attempt_id=a.id AND f.partition_id=p.id
  AND f.generation=:generation AND f.status='VERIFIED'
  AND f.object_version=:object_version AND f.verified_sha256=:sha256
  AND f.verified_size_bytes=:size_bytes
  AND NOT EXISTS (SELECT 1 FROM accepted_results AS r WHERE r.partition_id=p.id)
""")


def classify(job, partition, attempt, generation, t):
    if generation != partition["generation"] or generation != attempt["generation"]:
        return "stale_generation"
    if job["status"] == "CANCELLED":
        return "job_cancelled"
    if job["status"] != "RUNNING":
        return "terminal_job"
    if attempt["status"] != "ACTIVE":
        return "attempt_terminal"
    if t >= attempt["lease_expires_at"] or t >= attempt["hard_deadline_at"]:
        return "lease_expired"
    return "result_conflict"


def publish(engine, worker, attempt_id, model):
    scope, key = f"worker:{worker}:complete", str(model.request_id)
    request_hash = fingerprint(model.model_dump(mode="json", exclude={"request_id"}) | {"attempt_id": attempt_id})
    try:
        with engine.begin() as c:
            outcome = publish_locked(c, worker, attempt_id, model, scope, key, request_hash)
        return outcome  # The transaction, including rejection audit, is committed.
    except IntegrityError:
        # Same request ID can race across jobs. Roll back, then read its winner.
        with engine.connect() as c:
            prior = receipt(c, scope, key, request_hash)
        if prior:
            return prior["status_code"], prior["response"]
        raise


def publish_locked(c, worker, attempt_id, model, scope, key, request_hash):
    job = optional(c, db.jobs, db.jobs.c.id == model.job_id, lock=True)
    partition = optional(c, db.partitions, db.partitions.c.id == model.partition_id, lock=True)
    attempt = optional(c, db.attempts, db.attempts.c.id == attempt_id, lock=True)
    prior = receipt(c, scope, key, request_hash)
    if prior:
        return prior["status_code"], prior["response"]

    def reject(code, status=409):
        # Only known, correctly linked entities enter event FKs. Never echo a URI.
        linked = bool(job and partition and attempt and partition["job_id"] == job["id"]
                      and attempt["partition_id"] == partition["id"])
        response = {"error": dict(code=code, message=code, retryable=False, outcome="rejected",
                                  request_id=key, details={})}
        if job:
            append_event(c, job, "PUBLICATION_REJECTED", worker, request_id=key,
                partition=partition["id"] if linked else None,
                attempt=attempt["id"] if linked else None,
                generation=attempt["generation"] if linked else None, details={"code": code})
        save_receipt(c, scope, key, request_hash, "complete", status, response,
            job_id=job["id"] if job else None, worker_session_id=worker,
            attempt_id=attempt["id"] if linked else None)
        return status, response

    if not job or not partition or not attempt:
        return reject("not_found", 404)
    if attempt["worker_session_id"] != worker:
        return reject("wrong_owner", 403)
    if partition["job_id"] != job["id"] or attempt["partition_id"] != partition["id"]:
        return reject("result_conflict")
    generation = int(model.generation)
    accepted = optional(c, db.accepted_results, db.accepted_results.c.partition_id == partition["id"])
    if accepted:
        # Immutable accepted metadata needs no artifact lock and no live clock.
        artifact = optional(c, db.artifacts, db.artifacts.c.id == accepted["artifact_id"])
        exact = (accepted["attempt_id"] == attempt_id and accepted["generation"] == generation
            and accepted["artifact_id"] == model.artifact_id and model.sha256 == artifact["verified_sha256"]
            and model.artifact_uri == artifact_uri(artifact)
            and accepted["publication_fingerprint"] == publication_fingerprint(model, attempt_id, artifact))
        if exact:
            return 200, {"accepted_result": accepted_response(accepted, artifact),
                         "replay": True, "job_status": job["status"]}
        return reject("stale_generation" if generation < partition["generation"] else "result_conflict")

    artifact = optional(c, db.artifacts, db.artifacts.c.id == model.artifact_id, lock=True)
    if not artifact:
        return reject("artifact_identity_mismatch")
    if artifact["status"] != "VERIFIED":
        return reject("artifact_not_verified")
    if (artifact["attempt_id"] != attempt_id or artifact["partition_id"] != partition["id"]
        or artifact["generation"] != generation or model.sha256 != artifact["verified_sha256"]
        or model.artifact_uri != artifact_uri(artifact)):
        return reject("stale_generation" if generation != partition["generation"] else "artifact_identity_mismatch")
    t = db_time(c)  # AFTER job -> partition -> attempt -> artifact locks.
    affected = c.execute(FENCED_UPDATE, dict(job_id=job["id"], partition_id=partition["id"],
        attempt_id=attempt_id, generation=generation, worker=worker, artifact_id=artifact["id"],
        object_version=artifact["object_version"], sha256=model.sha256,
        size_bytes=artifact["verified_size_bytes"], t=t)).rowcount
    if affected != 1:
        return reject(classify(job, partition, attempt, generation, t))
    digest = publication_fingerprint(model, attempt_id, artifact)
    result = dict(c.execute(db.accepted_results.insert().values(partition_id=partition["id"],
        attempt_id=attempt_id, generation=generation, artifact_id=artifact["id"],
        accepted_at=t, publication_fingerprint=digest).returning(db.accepted_results)).mappings().one())
    c.execute(db.attempts.update().where(db.attempts.c.id == attempt_id).values(status="SUCCEEDED", finished_at=t))
    for event_type, before, after in (("ATTEMPT_SUCCEEDED", "ACTIVE", "SUCCEEDED"),
                                     ("PARTITION_SUCCEEDED", "RUNNING", "SUCCEEDED"),
                                     ("RESULT_ACCEPTED", None, None)):
        append_event(c, job, event_type, worker, partition=partition["id"], attempt=attempt_id,
            generation=generation, occurred_at=t, from_state=before, to_state=after, request_id=key,
            details={"artifact_id": str(artifact["id"])} if event_type == "RESULT_ACCEPTED" else {})
    finish_job(c, job, t, worker, request_id=key)
    return 201, {"accepted_result": accepted_response(result, artifact), "replay": False, "job_status": job["status"]}
