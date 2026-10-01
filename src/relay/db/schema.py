"""Explicit SQLAlchemy Core metadata. Frozen Alembic SQL owns deployed DDL."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = sa.MetaData(naming_convention={
    "pk": "pk_%(table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
})


def uid(name, *, primary_key=False, nullable=False, references=None):
    args = [sa.ForeignKey(references, ondelete="RESTRICT")] if references else []
    return sa.Column(name, UUID(as_uuid=True), *args, primary_key=primary_key, nullable=nullable)


def stamp(name, *, nullable=False, default=True):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.text("clock_timestamp()") if default else None)


def check(expression, name):
    return sa.CheckConstraint(expression, name=name)


def hashes(*names):
    return [check(f"{name} ~ '^[0-9a-f]{{64}}$'", name + "_format") for name in names]


jobs = sa.Table("jobs", metadata,
    uid("id", primary_key=True), sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    uid("parent_job_id", nullable=True, references="jobs.id"),
    sa.Column("status", sa.Text, nullable=False, server_default="QUEUED"),
    sa.Column("definition_hash", sa.Text, nullable=False),
    sa.Column("workload_name", sa.Text, nullable=False),
    sa.Column("workload_version", sa.Text, nullable=False),
    sa.Column("workload_digest", sa.Text, nullable=False),
    sa.Column("parameters", JSONB, nullable=False), sa.Column("manifest_hash", sa.Text, nullable=False),
    sa.Column("max_attempts", sa.Integer, nullable=False, server_default="5"),
    sa.Column("lease_seconds", sa.Integer, nullable=False, server_default="30"),
    sa.Column("max_attempt_seconds", sa.Integer, nullable=False, server_default="600"),
    sa.Column("partition_count", sa.Integer, nullable=False),
    sa.Column("next_event_seq", sa.BigInteger, nullable=False, server_default="1"),
    sa.Column("fair_ticket", sa.BigInteger, nullable=False),
    stamp("created_at"), stamp("started_at", nullable=True, default=False),
    stamp("finished_at", nullable=True, default=False), sa.Column("cancellation_reason", sa.Text),
    # Internal guard support: never used as generation, time or authority.
    sa.Column("creation_xid", sa.Text, nullable=False, server_default=sa.text("pg_current_xact_id()::text")),
    check("version = 1", "version"), check("status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')", "status"),
    check("max_attempts BETWEEN 1 AND 10", "attempt_budget"),
    check("max_attempt_seconds BETWEEN 60 AND 3600 AND lease_seconds > 0 AND lease_seconds <= max_attempt_seconds", "lease_policy"),
    check("partition_count BETWEEN 1 AND 4096", "partition_count"),
    check("next_event_seq > 0 AND fair_ticket > 0", "counters"),
    check("workload_digest ~ '^(sha256:)?[0-9a-f]{64}$'", "workload_digest"),
    *hashes("definition_hash", "manifest_hash"),
)
sa.Index("ix_jobs_active_fair", jobs.c.fair_ticket, jobs.c.created_at, jobs.c.id,
         postgresql_where=jobs.c.status.in_(["QUEUED", "RUNNING"]))

input_artifacts = sa.Table("input_artifacts", metadata,
    uid("id", primary_key=True), sa.Column("import_key", sa.Text, nullable=False, unique=True),
    sa.Column("reservation_fingerprint", sa.Text, nullable=False),
    sa.Column("expected_sha256", sa.Text, nullable=False), sa.Column("size_bytes", sa.BigInteger, nullable=False),
    sa.Column("media_type", sa.Text, nullable=False), sa.Column("schema_hash", sa.Text, nullable=False),
    sa.Column("row_count", sa.BigInteger), sa.Column("status", sa.Text, nullable=False, server_default="RESERVED"),
    sa.Column("bucket", sa.Text, nullable=False), sa.Column("object_key", sa.Text, nullable=False, unique=True),
    sa.Column("object_version", sa.Text), sa.Column("sha256", sa.Text), stamp("created_at"),
    stamp("verified_at", nullable=True, default=False), sa.Column("error_code", sa.Text),
    sa.UniqueConstraint("bucket", "object_key", "object_version"),
    check("status IN ('RESERVED','VERIFIED','REJECTED')", "status"),
    check("size_bytes >= 0 AND (row_count IS NULL OR row_count >= 0)", "counts"),
    check("status <> 'VERIFIED' OR (object_version IS NOT NULL AND length(object_version) > 0 AND sha256 IS NOT NULL AND sha256 = expected_sha256 AND row_count IS NOT NULL AND verified_at IS NOT NULL)", "verified"),
    *hashes("reservation_fingerprint", "expected_sha256", "schema_hash", "sha256"),
)
sa.Index("ix_input_artifacts_reconciliation", input_artifacts.c.status, input_artifacts.c.created_at)

job_inputs = sa.Table("job_inputs", metadata,
    uid("job_id", primary_key=True, references="jobs.id"),
    sa.Column("input_ordinal", sa.Integer, primary_key=True), uid("input_artifact_id", references="input_artifacts.id"),
    stamp("created_at"), sa.UniqueConstraint("job_id", "input_artifact_id"),
    check("input_ordinal >= 0", "ordinal"),
)

partitions = sa.Table("partitions", metadata,
    uid("id", primary_key=True), uid("job_id", references="jobs.id"),
    sa.Column("ordinal", sa.Integer, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default="READY"),
    sa.Column("generation", sa.BigInteger, nullable=False, server_default="0"),
    sa.Column("latest_generation_fk", sa.BigInteger), stamp("eligible_at"), stamp("created_at"),
    stamp("started_at", nullable=True, default=False), stamp("finished_at", nullable=True, default=False),
    sa.Column("last_error_code", sa.Text), sa.UniqueConstraint("job_id", "ordinal"), sa.UniqueConstraint("id", "job_id"),
    sa.ForeignKeyConstraint(["id", "latest_generation_fk"], ["attempts.partition_id", "attempts.generation"],
                            name="fk_partitions_latest_attempt", ondelete="RESTRICT", deferrable=True,
                            initially="DEFERRED", use_alter=True),
    check("ordinal >= 0", "ordinal"), check("generation >= 0", "generation"),
    check("(generation = 0 AND latest_generation_fk IS NULL) OR (generation > 0 AND latest_generation_fk IS NOT NULL AND latest_generation_fk = generation)", "generation_projection"),
    check("status IN ('READY','RUNNING','SUCCEEDED','FAILED','CANCELLED')", "status"),
)
sa.Index("ix_partitions_ready", partitions.c.job_id, partitions.c.eligible_at, partitions.c.ordinal,
         postgresql_where=partitions.c.status == "READY")
sa.Index("ix_partitions_job_status", partitions.c.job_id, partitions.c.status)

partition_inputs = sa.Table("partition_inputs", metadata,
    uid("partition_id", primary_key=True, references="partitions.id"),
    sa.Column("slice_ordinal", sa.Integer, primary_key=True), uid("job_id"),
    sa.Column("input_ordinal", sa.Integer, nullable=False), sa.Column("first_row", sa.BigInteger, nullable=False),
    sa.Column("row_count", sa.BigInteger, nullable=False), stamp("created_at"),
    sa.ForeignKeyConstraint(["partition_id", "job_id"], ["partitions.id", "partitions.job_id"], name="fk_partition_inputs_partition_job", ondelete="RESTRICT"),
    sa.ForeignKeyConstraint(["job_id", "input_ordinal"], ["job_inputs.job_id", "job_inputs.input_ordinal"], ondelete="RESTRICT"),
    check("slice_ordinal >= 0 AND input_ordinal >= 0 AND first_row >= 0 AND row_count >= 0", "bounds"),
)

workers = sa.Table("workers", metadata,
    uid("session_id", primary_key=True), sa.Column("display_name", sa.Text, nullable=False),
    sa.Column("registration_hash", sa.Text, nullable=False), sa.Column("session_secret_hash", sa.Text, nullable=False),
    sa.Column("state", sa.Text, nullable=False, server_default="REGISTERED"),
    sa.Column("deployment_workload_digest", sa.Text, nullable=False),
    sa.Column("last_heartbeat_seq", sa.BigInteger, nullable=False, server_default="0"),
    sa.Column("next_event_seq", sa.BigInteger, nullable=False, server_default="1"),
    stamp("created_at"), stamp("last_seen_at"), stamp("stopped_at", nullable=True, default=False),
    check("state IN ('REGISTERED','DRAINING','STOPPED')", "state"),
    check("last_heartbeat_seq >= 0 AND next_event_seq > 0", "sequences"),
    check("deployment_workload_digest ~ '^(sha256:)?[0-9a-f]{64}$'", "workload_digest"),
    *hashes("registration_hash", "session_secret_hash"),
)
sa.Index("ix_workers_liveness", workers.c.last_seen_at, postgresql_where=workers.c.state != "STOPPED")

attempts = sa.Table("attempts", metadata,
    uid("id", primary_key=True), uid("partition_id", references="partitions.id"),
    sa.Column("generation", sa.BigInteger, nullable=False), uid("worker_session_id", references="workers.session_id"),
    sa.Column("status", sa.Text, nullable=False, server_default="ACTIVE"), stamp("claimed_at"),
    stamp("lease_expires_at", default=False), stamp("hard_deadline_at", default=False),
    sa.Column("last_renew_seq", sa.BigInteger, nullable=False, server_default="0"),
    sa.Column("last_renew_fingerprint", sa.Text), sa.Column("last_renew_response", JSONB),
    stamp("finished_at", nullable=True, default=False), sa.Column("failure_code", sa.Text),
    sa.Column("failure_detail", JSONB), sa.Column("failure_fingerprint", sa.Text),
    sa.UniqueConstraint("partition_id", "generation"), sa.UniqueConstraint("id", "partition_id", "generation"),
    check("generation > 0 AND last_renew_seq >= 0", "counters"),
    check("claimed_at < lease_expires_at AND lease_expires_at <= hard_deadline_at", "deadlines"),
    check("status IN ('ACTIVE','SUCCEEDED','FAILED','EXPIRED','CANCELLED')", "status"),
    *hashes("last_renew_fingerprint", "failure_fingerprint"),
)
sa.Index("uq_attempts_active_partition", attempts.c.partition_id, unique=True, postgresql_where=attempts.c.status == "ACTIVE")
sa.Index("uq_attempts_active_worker", attempts.c.worker_session_id, unique=True, postgresql_where=attempts.c.status == "ACTIVE")
sa.Index("ix_attempts_expiry", attempts.c.lease_expires_at, attempts.c.partition_id, postgresql_where=attempts.c.status == "ACTIVE")

artifacts = sa.Table("artifacts", metadata,
    uid("id", primary_key=True), uid("attempt_id"), uid("partition_id"), sa.Column("generation", sa.BigInteger, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default="RESERVED"),
    sa.Column("expected_sha256", sa.Text, nullable=False), sa.Column("expected_size_bytes", sa.BigInteger, nullable=False),
    sa.Column("expected_schema_hash", sa.Text, nullable=False), sa.Column("reservation_fingerprint", sa.Text, nullable=False),
    sa.Column("bucket", sa.Text, nullable=False), sa.Column("object_key", sa.Text, nullable=False),
    sa.Column("object_version", sa.Text), sa.Column("verified_sha256", sa.Text),
    sa.Column("verified_size_bytes", sa.BigInteger), sa.Column("verified_schema_hash", sa.Text),
    stamp("created_at"), stamp("verified_at", nullable=True, default=False), sa.Column("rejection_code", sa.Text),
    sa.ForeignKeyConstraint(["attempt_id", "partition_id", "generation"], ["attempts.id", "attempts.partition_id", "attempts.generation"], ondelete="RESTRICT"),
    sa.UniqueConstraint("attempt_id"), sa.UniqueConstraint("id", "attempt_id", "partition_id", "generation"),
    sa.UniqueConstraint("bucket", "object_key"), sa.UniqueConstraint("bucket", "object_key", "object_version"),
    check("generation > 0 AND expected_size_bytes BETWEEN 0 AND 268435456 AND (verified_size_bytes IS NULL OR verified_size_bytes >= 0)", "bounds"),
    check("status IN ('RESERVED','VERIFIED','REJECTED')", "status"),
    check("status <> 'VERIFIED' OR (object_version IS NOT NULL AND length(object_version) > 0 AND verified_sha256 IS NOT NULL AND verified_size_bytes IS NOT NULL AND verified_schema_hash IS NOT NULL AND verified_at IS NOT NULL AND verified_sha256 = expected_sha256 AND verified_size_bytes = expected_size_bytes AND verified_schema_hash = expected_schema_hash)", "verified"),
    *hashes("expected_sha256", "expected_schema_hash", "reservation_fingerprint", "verified_sha256", "verified_schema_hash"),
)
sa.Index("ix_artifacts_reconciliation", artifacts.c.status, artifacts.c.created_at)

accepted_results = sa.Table("accepted_results", metadata,
    uid("partition_id", primary_key=True, references="partitions.id"), uid("attempt_id"),
    sa.Column("generation", sa.BigInteger, nullable=False), uid("artifact_id"), stamp("accepted_at"),
    sa.Column("publication_fingerprint", sa.Text, nullable=False), sa.UniqueConstraint("artifact_id"), sa.UniqueConstraint("attempt_id"),
    sa.ForeignKeyConstraint(["attempt_id", "partition_id", "generation"], ["attempts.id", "attempts.partition_id", "attempts.generation"], ondelete="RESTRICT"),
    sa.ForeignKeyConstraint(["artifact_id", "attempt_id", "partition_id", "generation"], ["artifacts.id", "artifacts.attempt_id", "artifacts.partition_id", "artifacts.generation"], ondelete="RESTRICT"),
    check("generation > 0", "generation"), *hashes("publication_fingerprint"),
)

events = sa.Table("events", metadata,
    uid("job_id", primary_key=True, references="jobs.id"), sa.Column("seq", sa.BigInteger, primary_key=True),
    uid("partition_id", nullable=True), uid("attempt_id", nullable=True), uid("attempt_partition_id", nullable=True),
    sa.Column("attempt_generation", sa.BigInteger), sa.Column("type", sa.Text, nullable=False), stamp("occurred_at"),
    sa.Column("request_id", sa.Text), sa.Column("actor_type", sa.Text, nullable=False), sa.Column("actor_id", sa.Text, nullable=False),
    sa.Column("from_state", sa.Text), sa.Column("to_state", sa.Text), sa.Column("details", JSONB, nullable=False),
    sa.ForeignKeyConstraint(["partition_id", "job_id"], ["partitions.id", "partitions.job_id"], ondelete="RESTRICT"),
    sa.ForeignKeyConstraint(["attempt_id", "attempt_partition_id", "attempt_generation"], ["attempts.id", "attempts.partition_id", "attempts.generation"], ondelete="RESTRICT", match="FULL"),
    check("seq > 0", "sequence"),
    check("num_nonnulls(attempt_id, attempt_partition_id, attempt_generation) IN (0,3)", "attempt_optional"),
    check("attempt_id IS NULL OR (partition_id IS NOT NULL AND attempt_partition_id = partition_id)", "attempt_partition"),
)
sa.Index("ix_events_cursor", events.c.job_id, events.c.partition_id, events.c.seq)

worker_events = sa.Table("worker_events", metadata,
    uid("session_id", primary_key=True, references="workers.session_id"), sa.Column("seq", sa.BigInteger, primary_key=True),
    sa.Column("type", sa.Text, nullable=False), stamp("occurred_at"), sa.Column("request_id", sa.Text),
    sa.Column("details", JSONB, nullable=False), check("seq > 0", "sequence"),
)
sa.Index("ix_worker_events_cursor", worker_events.c.session_id, worker_events.c.occurred_at)

request_receipts = sa.Table("request_receipts", metadata,
    sa.Column("scope", sa.Text, primary_key=True), sa.Column("key", sa.String(128), primary_key=True),
    sa.Column("request_hash", sa.Text, nullable=False), sa.Column("operation", sa.Text, nullable=False),
    uid("job_id", nullable=True, references="jobs.id"), uid("worker_session_id", nullable=True, references="workers.session_id"),
    uid("attempt_id", nullable=True, references="attempts.id"), sa.Column("status_code", sa.Integer, nullable=False),
    sa.Column("response", JSONB, nullable=False), stamp("created_at"),
    check("length(key) BETWEEN 1 AND 128 AND length(scope) > 0", "key"),
    check("status_code BETWEEN 100 AND 599", "status_code"), *hashes("request_hash"),
)
sa.Index("ix_request_receipts_job", request_receipts.c.job_id)
sa.Index("ix_request_receipts_worker", request_receipts.c.worker_session_id, request_receipts.c.created_at)

scheduler_state = sa.Table("scheduler_state", metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=False), sa.Column("next_ticket", sa.BigInteger, nullable=False),
    stamp("updated_at"), check("id = 1", "singleton"), check("next_ticket > 0", "ticket"),
)
