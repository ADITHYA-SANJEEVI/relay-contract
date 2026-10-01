"""Explicit runtime-only transactions. No publication, renewal or settlement."""

import hashlib
import secrets
from datetime import timedelta
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from relay.db import schema as db
from relay.workloads.reference import INPUT_SCHEMA_HASH, OUTPUT_SCHEMA_HASH, WORKLOAD, WORKLOAD_DIGEST

from .common import Rejection, append_event, canonical, db_time, fingerprint, one, receipt, save_receipt, wire


def input_response(row):
    return wire({"id": row["id"], "status": row["status"], "sha256": row["sha256"],
        "media_type": row["media_type"],
        "expected_sha256": row["expected_sha256"], "size_bytes": str(row["size_bytes"]),
        "schema_hash": row["schema_hash"], "row_count": None if row["row_count"] is None else str(row["row_count"]),
        "object_version": row["object_version"], "created_at": row["created_at"], "verified_at": row["verified_at"],
        "error_code": row["error_code"], "upload_url": f"/v1/inputs/{row['id']}/content"})


def artifact_response(row):
    return wire({"id": row["id"], "attempt_id": row["attempt_id"], "partition_id": row["partition_id"],
        "generation": str(row["generation"]), "status": row["status"],
        "sha256": row["verified_sha256"], "size_bytes": None if row["verified_size_bytes"] is None else str(row["verified_size_bytes"]),
        "schema_hash": row["verified_schema_hash"], "object_version": row["object_version"],
        "verified_at": row["verified_at"], "rejection_code": row["rejection_code"],
        "upload_url": f"/v1/artifacts/{row['id']}/content"})


class Control:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings
        self.operator_identity = hashlib.sha256(settings["RELAY_OPERATOR_TOKEN"].encode()).hexdigest()
        with engine.connect() as c:
            if c.scalar(sa.text("SELECT current_user")) != "relay_runtime":
                raise ValueError("Application operations require relay_runtime")

    def authenticate_worker(self, session, secret):
        if not secret: raise Rejection("unauthenticated", 401)
        with self.engine.connect() as c:
            row = c.execute(sa.select(db.workers).where(db.workers.c.session_id == session)).mappings().first()
        if not row or not secrets.compare_digest(row["session_secret_hash"], hashlib.sha256(secret.encode()).hexdigest()):
            raise Rejection("unauthenticated", 401)
        return session

    def reserve_input(self, key, model):
        body = model.model_dump(mode="json")
        if body["schema_hash"] != INPUT_SCHEMA_HASH: raise Rejection("schema_mismatch", 422)
        if int(body["size_bytes"]) > int(self.settings.get("RELAY_MAX_INPUT_BYTES", 268435456)):
            raise Rejection("input_too_large", 422)
        digest = fingerprint(body)
        import_key = fingerprint({"operator": self.operator_identity, "key": key})

        def existing(c):
            row = c.execute(sa.select(db.input_artifacts).where(db.input_artifacts.c.import_key == import_key)).mappings().first()
            if row:
                if row["reservation_fingerprint"] != digest: raise Rejection("idempotency_conflict")
                return input_response(row)
        try:
            with self.engine.begin() as c:
                prior = existing(c)
                if prior: return 200, prior
                identity = uuid4()
                row = c.execute(db.input_artifacts.insert().values(id=identity, import_key=import_key,
                    reservation_fingerprint=digest, expected_sha256=body["sha256"], size_bytes=int(body["size_bytes"]),
                    media_type=body["media_type"], schema_hash=body["schema_hash"], bucket=self.settings["S3_BUCKET"],
                    object_key=f"inputs/{identity}/input.parquet").returning(db.input_artifacts)).mappings().one()
                response = input_response(row)
            return 201, response
        except IntegrityError:
            # Expected natural-key race: fresh transaction reads committed winner.
            with self.engine.connect() as c:
                prior = existing(c)
            if prior: return 200, prior
            raise

    def verified_inputs(self, c, references):
        rows = []
        for ref in references:
            row = one(c, db.input_artifacts, db.input_artifacts.c.id == ref.artifact_id)
            if row["status"] != "VERIFIED": raise Rejection("input_not_verified", 422)
            if row["schema_hash"] != INPUT_SCHEMA_HASH: raise Rejection("schema_mismatch", 422)
            rows.append(row)
        return rows

    def validate_manifest(self, model, inputs):
        if model.workload.model_dump() != WORKLOAD: raise Rejection("unsupported_workload", 422)
        if model.policy.lease_seconds > model.policy.max_attempt_seconds: raise Rejection("invalid_policy", 422)
        if [x.input_ordinal for x in model.inputs] != list(range(len(model.inputs))): raise Rejection("input_ordinals", 422)
        if len({x.artifact_id for x in model.inputs}) != len(model.inputs): raise Rejection("duplicate_input", 422)
        if [x.ordinal for x in model.partitions] != list(range(len(model.partitions))): raise Rejection("partition_ordinals", 422)
        ranges = [[] for _ in inputs]
        for partition in model.partitions:
            for part in partition.slices:
                if part.input_ordinal >= len(inputs): raise Rejection("unknown_input_ordinal", 422)
                start, count = int(part.first_row), int(part.row_count)
                if start + count > inputs[part.input_ordinal]["row_count"]: raise Rejection("manifest_bounds", 422)
                ranges[part.input_ordinal].append((start, count))
        for row, intervals in zip(inputs, ranges):
            if row["row_count"] == 0:
                if intervals != [(0, 0)]: raise Rejection("empty_input_slice", 422)
                continue
            end = 0
            for start, count in sorted(intervals):
                if count <= 0 or start != end: raise Rejection("manifest_coverage", 422)
                end = start + count
            if end != row["row_count"]: raise Rejection("manifest_coverage", 422)

    def submit(self, key, model):
        scope = f"operator:{self.operator_identity}:submit"
        body = model.model_dump(mode="json")
        with self.engine.connect() as c:
            inputs = self.verified_inputs(c, model.inputs)
        self.validate_manifest(model, inputs)
        snapshot = [wire({k: row[k] for k in ("id", "object_version", "sha256", "size_bytes", "schema_hash", "row_count")}) for row in inputs]
        definition = body | {"input_snapshots": snapshot}
        if len(canonical(definition)) > 1048576: raise Rejection("descriptor_too_large", 422)
        digest = fingerprint(definition)
        with self.engine.begin() as c:
            scheduler = one(c, db.scheduler_state, db.scheduler_state.c.id == 1, lock=True)
            prior = receipt(c, scope, key, digest)
            if prior: return 200, prior["response"]
            rechecked = self.verified_inputs(c, model.inputs)
            if inputs != rechecked: raise Rejection("input_identity_changed")
            if model.parent_job_id:
                one(c, db.jobs, db.jobs.c.id == model.parent_job_id)
            identity = uuid4()
            job = dict(c.execute(db.jobs.insert().values(id=identity, parent_job_id=model.parent_job_id,
                definition_hash=digest, workload_name=model.workload.name, workload_version=model.workload.version,
                workload_digest=model.workload.digest, parameters=model.parameters.model_dump(),
                manifest_hash=fingerprint(body["partitions"]), partition_count=len(model.partitions),
                fair_ticket=scheduler["next_ticket"], **model.policy.model_dump()).returning(db.jobs)).mappings().one())
            c.execute(db.job_inputs.insert(), [dict(job_id=identity, input_ordinal=ref.input_ordinal,
                      input_artifact_id=ref.artifact_id) for ref in model.inputs])
            for descriptor in model.partitions:
                partition = uuid4()
                c.execute(db.partitions.insert().values(id=partition, job_id=identity, ordinal=descriptor.ordinal))
                c.execute(db.partition_inputs.insert(), [dict(partition_id=partition, slice_ordinal=i, job_id=identity,
                    input_ordinal=s.input_ordinal, first_row=int(s.first_row), row_count=int(s.row_count))
                    for i, s in enumerate(descriptor.slices)])
            append_event(c, job, "JOB_SUBMITTED", "operator", to_state="QUEUED")
            response = wire({"id": identity, "definition_hash": digest, "status": "QUEUED"})
            save_receipt(c, scope, key, digest, "submit", 201, response, job_id=identity)
            c.execute(db.scheduler_state.update().where(db.scheduler_state.c.id == 1).values(
                next_ticket=scheduler["next_ticket"] + 1, updated_at=sa.func.clock_timestamp()))
        return 201, response

    def register(self, model):
        if model.deployment_workload_digest != WORKLOAD_DIGEST: raise Rejection("unsupported_workload", 422)
        body = model.model_dump(mode="json")
        secret_hash = hashlib.sha256(body.pop("session_secret").encode()).hexdigest()
        binding_hash = fingerprint(body | {"session_secret_hash": secret_hash})

        def existing(c):
            row = c.execute(sa.select(db.workers).where(db.workers.c.session_id == model.session_id).with_for_update()).mappings().first()
            if row:
                if row["registration_hash"] != binding_hash: raise Rejection("registration_conflict")
                return wire({"session_id": row["session_id"], "state": row["state"]})
        try:
            with self.engine.begin() as c:
                prior = existing(c)
                if prior: return 200, prior
                # Serialize registration capacity without the claim scheduler row.
                c.execute(sa.text("LOCK TABLE workers IN SHARE ROW EXCLUSIVE MODE"))
                prior = existing(c)
                if prior: return 200, prior
                capacity = int(self.settings.get("RELAY_MAX_WORKERS", 32))
                if c.scalar(sa.select(sa.func.count()).select_from(db.workers).where(db.workers.c.state != "STOPPED")) >= capacity:
                    raise Rejection("worker_capacity", 429)
                c.execute(db.workers.insert().values(session_id=model.session_id, display_name=model.display_name,
                    registration_hash=binding_hash, session_secret_hash=secret_hash,
                    deployment_workload_digest=model.deployment_workload_digest, next_event_seq=2))
                c.execute(db.worker_events.insert().values(session_id=model.session_id, seq=1, type="WORKER_REGISTERED", details={}))
                response = wire({"session_id": model.session_id, "state": "REGISTERED"})
            return 201, response
        except IntegrityError:
            with self.engine.begin() as c:
                prior = existing(c)
            if prior: return 200, prior
            raise

    def claim(self, worker, key):
        scope, digest = f"worker:{worker}:claim", fingerprint({})
        with self.engine.connect() as c:
            prior = receipt(c, scope, key, digest)
            if prior: return self.replay_claim(prior)
        with self.engine.begin() as c:
            scheduler = one(c, db.scheduler_state, db.scheduler_state.c.id == 1, lock=True)
            prior = receipt(c, scope, key, digest)
            if prior: return self.replay_claim(prior)
            # Discovery is unlocked; recheck after acquiring job and partition locks.
            while True:
                candidate = c.scalar(sa.select(db.jobs.c.id).where(db.jobs.c.status.in_(["QUEUED", "RUNNING"]),
                    sa.exists(sa.select(1).where(db.partitions.c.job_id == db.jobs.c.id,
                        db.partitions.c.status == "READY", db.partitions.c.eligible_at <= sa.func.clock_timestamp(),
                        db.partitions.c.generation < db.jobs.c.max_attempts))).order_by(
                            db.jobs.c.fair_ticket, db.jobs.c.created_at, db.jobs.c.id).limit(1))
                if candidate is None: break
                job = one(c, db.jobs, db.jobs.c.id == candidate, lock=True)
                if job["status"] not in ("QUEUED", "RUNNING"): continue
                partition = c.execute(sa.select(db.partitions).where(db.partitions.c.job_id == candidate,
                    db.partitions.c.status == "READY", db.partitions.c.eligible_at <= sa.func.clock_timestamp(),
                    db.partitions.c.generation < job["max_attempts"]).order_by(db.partitions.c.ordinal).limit(1)
                    .with_for_update()).mappings().first()
                if partition: break
            worker_row = one(c, db.workers, db.workers.c.session_id == worker, lock=True)
            if worker_row["state"] != "REGISTERED": raise Rejection("worker_draining")
            if worker_row["deployment_workload_digest"] != WORKLOAD_DIGEST: raise Rejection("unsupported_workload")
            if c.scalar(sa.select(sa.exists().where(db.attempts.c.worker_session_id == worker, db.attempts.c.status == "ACTIVE"))):
                raise Rejection("worker_busy")
            if candidate is None:
                save_receipt(c, scope, key, digest, "claim", 204, {}, worker_session_id=worker)
                return 204, None
            t = db_time(c)  # AFTER scheduler, job, partition and worker locks.
            if partition["eligible_at"] > t: raise Rejection("partition_not_eligible")
            generation, attempt = partition["generation"] + 1, uuid4()
            lease, hard = t + timedelta(seconds=job["lease_seconds"]), t + timedelta(seconds=job["max_attempt_seconds"])
            c.execute(db.attempts.insert().values(id=attempt, partition_id=partition["id"], generation=generation,
                worker_session_id=worker, claimed_at=t, lease_expires_at=lease, hard_deadline_at=hard))
            c.execute(db.partitions.update().where(db.partitions.c.id == partition["id"]).values(status="RUNNING",
                generation=generation, latest_generation_fk=generation, started_at=partition["started_at"] or t))
            c.execute(db.jobs.update().where(db.jobs.c.id == job["id"]).values(status="RUNNING",
                started_at=job["started_at"] or t, fair_ticket=scheduler["next_ticket"]))
            c.execute(db.scheduler_state.update().where(db.scheduler_state.c.id == 1).values(
                next_ticket=scheduler["next_ticket"] + 1, updated_at=t))
            append_event(c, job, "ATTEMPT_CLAIMED", worker, partition=partition["id"], attempt=attempt,
                         generation=generation, to_state="ACTIVE", occurred_at=t)
            append_event(c, job, "PARTITION_RUNNING", worker, partition=partition["id"],
                         from_state="READY", to_state="RUNNING", occurred_at=t)
            if job["status"] == "QUEUED":
                append_event(c, job, "JOB_RUNNING", worker, from_state="QUEUED", to_state="RUNNING", occurred_at=t)
            slices = c.execute(sa.select(db.partition_inputs.c.slice_ordinal, db.partition_inputs.c.first_row,
                db.partition_inputs.c.row_count, db.input_artifacts.c.id.label("input_artifact_id"),
                db.input_artifacts.c.object_version, db.input_artifacts.c.sha256, db.input_artifacts.c.schema_hash)
                .join(db.job_inputs, sa.and_(db.job_inputs.c.job_id == db.partition_inputs.c.job_id,
                                           db.job_inputs.c.input_ordinal == db.partition_inputs.c.input_ordinal))
                .join(db.input_artifacts, db.input_artifacts.c.id == db.job_inputs.c.input_artifact_id)
                .where(db.partition_inputs.c.partition_id == partition["id"]).order_by(db.partition_inputs.c.slice_ordinal)).mappings().all()
            response = wire(dict(job_id=job["id"], partition_id=partition["id"], ordinal=partition["ordinal"],
                attempt_id=attempt, generation=str(generation), worker_session_id=worker, claimed_at=t,
                lease_expires_at=lease, hard_deadline_at=hard, renew_after_seconds=10,
                workload=WORKLOAD, parameters=job["parameters"], replay=False,
                inputs=[dict(input_artifact_id=s["input_artifact_id"], object_version=s["object_version"],
                    sha256=s["sha256"], schema_hash=s["schema_hash"], first_row=str(s["first_row"]), row_count=str(s["row_count"]),
                    download_url=f"/v1/attempts/{attempt}/inputs/{s['slice_ordinal']}/content") for s in slices]))
            save_receipt(c, scope, key, digest, "claim", 201, response, job_id=job["id"], worker_session_id=worker, attempt_id=attempt)
        return 201, response

    @staticmethod
    def replay_claim(prior):
        if prior["status_code"] == 204: return 204, None
        return 200, prior["response"] | {"replay": True}

    def reserve_artifact(self, worker, attempt_id, model):
        if model.schema_hash != OUTPUT_SCHEMA_HASH: raise Rejection("schema_mismatch", 422)
        size = int(model.size_bytes)
        if size > 268435456: raise Rejection("output_too_large", 422)
        digest = fingerprint(model.model_dump(mode="json") | {"attempt_id": attempt_id})
        with self.engine.begin() as c:
            job = one(c, db.jobs, db.jobs.c.id == model.job_id, lock=True)
            partition = one(c, db.partitions, db.partitions.c.id == model.partition_id, lock=True)
            attempt = one(c, db.attempts, db.attempts.c.id == attempt_id, lock=True)
            t = db_time(c)  # AFTER the final authoritative lock.
            if attempt["worker_session_id"] != worker: raise Rejection("wrong_owner", 403)
            generation = int(model.generation)
            live = (job["status"] == "RUNNING" and partition["status"] == "RUNNING"
                and partition["job_id"] == job["id"] and attempt["partition_id"] == partition["id"]
                and partition["generation"] == generation == partition["latest_generation_fk"] == attempt["generation"]
                and attempt["status"] == "ACTIVE")
            if not live: raise Rejection("ownership_conflict")
            if not t < attempt["lease_expires_at"] or not t < attempt["hard_deadline_at"]:
                raise Rejection("lease_expired")
            prior = c.execute(sa.select(db.artifacts).where(db.artifacts.c.attempt_id == attempt_id)).mappings().first()
            if prior:
                if prior["reservation_fingerprint"] != digest: raise Rejection("artifact_identity_mismatch")
                return 200, artifact_response(prior)
            identity = uuid4()
            key = f"jobs/{job['id']}/partitions/{partition['ordinal']}/attempt-{generation}/{identity}/output.parquet"
            row = c.execute(db.artifacts.insert().values(id=identity, attempt_id=attempt_id,
                partition_id=partition["id"], generation=generation, expected_sha256=model.sha256,
                expected_size_bytes=size, expected_schema_hash=model.schema_hash, reservation_fingerprint=digest,
                bucket=self.settings["S3_BUCKET"], object_key=key).returning(db.artifacts)).mappings().one()
            response = artifact_response(row)
            append_event(c, job, "ARTIFACT_RESERVED", worker, partition=partition["id"], attempt=attempt_id,
                         generation=generation, occurred_at=t, details={"artifact_id": str(identity)})
        return 201, response
