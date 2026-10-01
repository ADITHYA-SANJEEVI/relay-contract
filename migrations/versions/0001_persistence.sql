-- Frozen M1A DDL compiled from reviewed explicit Core metadata.

CREATE TABLE input_artifacts (
	id UUID NOT NULL,
	import_key TEXT NOT NULL,
	reservation_fingerprint TEXT NOT NULL,
	expected_sha256 TEXT NOT NULL,
	size_bytes BIGINT NOT NULL,
	media_type TEXT NOT NULL,
	schema_hash TEXT NOT NULL,
	row_count BIGINT,
	status TEXT DEFAULT 'RESERVED' NOT NULL,
	bucket TEXT NOT NULL,
	object_key TEXT NOT NULL,
	object_version TEXT,
	sha256 TEXT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	verified_at TIMESTAMP WITH TIME ZONE,
	error_code TEXT,
	CONSTRAINT pk_input_artifacts PRIMARY KEY (id),
	CONSTRAINT uq_input_artifacts_bucket_object_key_object_version UNIQUE (bucket, object_key, object_version),
	CONSTRAINT ck_input_artifacts_status CHECK (status IN ('RESERVED','VERIFIED','REJECTED')),
	CONSTRAINT ck_input_artifacts_counts CHECK (size_bytes >= 0 AND (row_count IS NULL OR row_count >= 0)),
	CONSTRAINT ck_input_artifacts_verified CHECK (status <> 'VERIFIED' OR (object_version IS NOT NULL AND length(object_version) > 0 AND sha256 IS NOT NULL AND sha256 = expected_sha256 AND row_count IS NOT NULL AND verified_at IS NOT NULL)),
	CONSTRAINT ck_input_artifacts_reservation_fingerprint_format CHECK (reservation_fingerprint ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_input_artifacts_expected_sha256_format CHECK (expected_sha256 ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_input_artifacts_schema_hash_format CHECK (schema_hash ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_input_artifacts_sha256_format CHECK (sha256 ~ '^[0-9a-f]{64}$'),
	CONSTRAINT uq_input_artifacts_import_key UNIQUE (import_key),
	CONSTRAINT uq_input_artifacts_object_key UNIQUE (object_key)
);

CREATE TABLE jobs (
	id UUID NOT NULL,
	version INTEGER DEFAULT '1' NOT NULL,
	parent_job_id UUID,
	status TEXT DEFAULT 'QUEUED' NOT NULL,
	definition_hash TEXT NOT NULL,
	workload_name TEXT NOT NULL,
	workload_version TEXT NOT NULL,
	workload_digest TEXT NOT NULL,
	parameters JSONB NOT NULL,
	manifest_hash TEXT NOT NULL,
	max_attempts INTEGER DEFAULT '5' NOT NULL,
	lease_seconds INTEGER DEFAULT '30' NOT NULL,
	max_attempt_seconds INTEGER DEFAULT '600' NOT NULL,
	partition_count INTEGER NOT NULL,
	next_event_seq BIGINT DEFAULT '1' NOT NULL,
	fair_ticket BIGINT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	finished_at TIMESTAMP WITH TIME ZONE,
	cancellation_reason TEXT,
	creation_xid TEXT DEFAULT pg_current_xact_id()::text NOT NULL,
	CONSTRAINT pk_jobs PRIMARY KEY (id),
	CONSTRAINT ck_jobs_version CHECK (version = 1),
	CONSTRAINT ck_jobs_status CHECK (status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
	CONSTRAINT ck_jobs_attempt_budget CHECK (max_attempts BETWEEN 1 AND 10),
	CONSTRAINT ck_jobs_lease_policy CHECK (max_attempt_seconds BETWEEN 60 AND 3600 AND lease_seconds > 0 AND lease_seconds <= max_attempt_seconds),
	CONSTRAINT ck_jobs_partition_count CHECK (partition_count BETWEEN 1 AND 4096),
	CONSTRAINT ck_jobs_counters CHECK (next_event_seq > 0 AND fair_ticket > 0),
	CONSTRAINT ck_jobs_workload_digest CHECK (workload_digest ~ '^(sha256:)?[0-9a-f]{64}$'),
	CONSTRAINT ck_jobs_definition_hash_format CHECK (definition_hash ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_jobs_manifest_hash_format CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
	CONSTRAINT fk_jobs_parent_job_id_jobs FOREIGN KEY(parent_job_id) REFERENCES jobs (id) ON DELETE RESTRICT
);

CREATE TABLE scheduler_state (
	id INTEGER NOT NULL,
	next_ticket BIGINT NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	CONSTRAINT pk_scheduler_state PRIMARY KEY (id),
	CONSTRAINT ck_scheduler_state_singleton CHECK (id = 1),
	CONSTRAINT ck_scheduler_state_ticket CHECK (next_ticket > 0)
);

CREATE TABLE workers (
	session_id UUID NOT NULL,
	display_name TEXT NOT NULL,
	registration_hash TEXT NOT NULL,
	session_secret_hash TEXT NOT NULL,
	state TEXT DEFAULT 'REGISTERED' NOT NULL,
	deployment_workload_digest TEXT NOT NULL,
	last_heartbeat_seq BIGINT DEFAULT '0' NOT NULL,
	next_event_seq BIGINT DEFAULT '1' NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	stopped_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_workers PRIMARY KEY (session_id),
	CONSTRAINT ck_workers_state CHECK (state IN ('REGISTERED','DRAINING','STOPPED')),
	CONSTRAINT ck_workers_sequences CHECK (last_heartbeat_seq >= 0 AND next_event_seq > 0),
	CONSTRAINT ck_workers_workload_digest CHECK (deployment_workload_digest ~ '^(sha256:)?[0-9a-f]{64}$'),
	CONSTRAINT ck_workers_registration_hash_format CHECK (registration_hash ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_workers_session_secret_hash_format CHECK (session_secret_hash ~ '^[0-9a-f]{64}$')
);

CREATE TABLE job_inputs (
	job_id UUID NOT NULL,
	input_ordinal INTEGER NOT NULL,
	input_artifact_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	CONSTRAINT pk_job_inputs PRIMARY KEY (job_id, input_ordinal),
	CONSTRAINT uq_job_inputs_job_id_input_artifact_id UNIQUE (job_id, input_artifact_id),
	CONSTRAINT ck_job_inputs_ordinal CHECK (input_ordinal >= 0),
	CONSTRAINT fk_job_inputs_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE RESTRICT,
	CONSTRAINT fk_job_inputs_input_artifact_id_input_artifacts FOREIGN KEY(input_artifact_id) REFERENCES input_artifacts (id) ON DELETE RESTRICT
);

CREATE TABLE partitions (
	id UUID NOT NULL,
	job_id UUID NOT NULL,
	ordinal INTEGER NOT NULL,
	status TEXT DEFAULT 'READY' NOT NULL,
	generation BIGINT DEFAULT '0' NOT NULL,
	latest_generation_fk BIGINT,
	eligible_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	finished_at TIMESTAMP WITH TIME ZONE,
	last_error_code TEXT,
	CONSTRAINT pk_partitions PRIMARY KEY (id),
	CONSTRAINT uq_partitions_job_id_ordinal UNIQUE (job_id, ordinal),
	CONSTRAINT uq_partitions_id_job_id UNIQUE (id, job_id),
	CONSTRAINT ck_partitions_ordinal CHECK (ordinal >= 0),
	CONSTRAINT ck_partitions_generation CHECK (generation >= 0),
	CONSTRAINT ck_partitions_generation_projection CHECK ((generation = 0 AND latest_generation_fk IS NULL) OR (generation > 0 AND latest_generation_fk IS NOT NULL AND latest_generation_fk = generation)),
	CONSTRAINT ck_partitions_status CHECK (status IN ('READY','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
	CONSTRAINT fk_partitions_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE RESTRICT
);

CREATE TABLE worker_events (
	session_id UUID NOT NULL,
	seq BIGINT NOT NULL,
	type TEXT NOT NULL,
	occurred_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	request_id TEXT,
	details JSONB NOT NULL,
	CONSTRAINT pk_worker_events PRIMARY KEY (session_id, seq),
	CONSTRAINT ck_worker_events_sequence CHECK (seq > 0),
	CONSTRAINT fk_worker_events_session_id_workers FOREIGN KEY(session_id) REFERENCES workers (session_id) ON DELETE RESTRICT
);

CREATE TABLE attempts (
	id UUID NOT NULL,
	partition_id UUID NOT NULL,
	generation BIGINT NOT NULL,
	worker_session_id UUID NOT NULL,
	status TEXT DEFAULT 'ACTIVE' NOT NULL,
	claimed_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	lease_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	hard_deadline_at TIMESTAMP WITH TIME ZONE NOT NULL,
	last_renew_seq BIGINT DEFAULT '0' NOT NULL,
	last_renew_fingerprint TEXT,
	last_renew_response JSONB,
	finished_at TIMESTAMP WITH TIME ZONE,
	failure_code TEXT,
	failure_detail JSONB,
	failure_fingerprint TEXT,
	CONSTRAINT pk_attempts PRIMARY KEY (id),
	CONSTRAINT uq_attempts_partition_id_generation UNIQUE (partition_id, generation),
	CONSTRAINT uq_attempts_id_partition_id_generation UNIQUE (id, partition_id, generation),
	CONSTRAINT ck_attempts_counters CHECK (generation > 0 AND last_renew_seq >= 0),
	CONSTRAINT ck_attempts_deadlines CHECK (claimed_at < lease_expires_at AND lease_expires_at <= hard_deadline_at),
	CONSTRAINT ck_attempts_status CHECK (status IN ('ACTIVE','SUCCEEDED','FAILED','EXPIRED','CANCELLED')),
	CONSTRAINT ck_attempts_last_renew_fingerprint_format CHECK (last_renew_fingerprint ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_attempts_failure_fingerprint_format CHECK (failure_fingerprint ~ '^[0-9a-f]{64}$'),
	CONSTRAINT fk_attempts_partition_id_partitions FOREIGN KEY(partition_id) REFERENCES partitions (id) ON DELETE RESTRICT,
	CONSTRAINT fk_attempts_worker_session_id_workers FOREIGN KEY(worker_session_id) REFERENCES workers (session_id) ON DELETE RESTRICT
);

CREATE TABLE partition_inputs (
	partition_id UUID NOT NULL,
	slice_ordinal INTEGER NOT NULL,
	job_id UUID NOT NULL,
	input_ordinal INTEGER NOT NULL,
	first_row BIGINT NOT NULL,
	row_count BIGINT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	CONSTRAINT pk_partition_inputs PRIMARY KEY (partition_id, slice_ordinal),
	CONSTRAINT fk_partition_inputs_partition_job FOREIGN KEY(partition_id, job_id) REFERENCES partitions (id, job_id) ON DELETE RESTRICT,
	CONSTRAINT fk_partition_inputs_job_id_job_inputs FOREIGN KEY(job_id, input_ordinal) REFERENCES job_inputs (job_id, input_ordinal) ON DELETE RESTRICT,
	CONSTRAINT ck_partition_inputs_bounds CHECK (slice_ordinal >= 0 AND input_ordinal >= 0 AND first_row >= 0 AND row_count >= 0),
	CONSTRAINT fk_partition_inputs_partition_id_partitions FOREIGN KEY(partition_id) REFERENCES partitions (id) ON DELETE RESTRICT
);

CREATE TABLE artifacts (
	id UUID NOT NULL,
	attempt_id UUID NOT NULL,
	partition_id UUID NOT NULL,
	generation BIGINT NOT NULL,
	status TEXT DEFAULT 'RESERVED' NOT NULL,
	expected_sha256 TEXT NOT NULL,
	expected_size_bytes BIGINT NOT NULL,
	expected_schema_hash TEXT NOT NULL,
	reservation_fingerprint TEXT NOT NULL,
	bucket TEXT NOT NULL,
	object_key TEXT NOT NULL,
	object_version TEXT,
	verified_sha256 TEXT,
	verified_size_bytes BIGINT,
	verified_schema_hash TEXT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	verified_at TIMESTAMP WITH TIME ZONE,
	rejection_code TEXT,
	CONSTRAINT pk_artifacts PRIMARY KEY (id),
	CONSTRAINT fk_artifacts_attempt_id_attempts FOREIGN KEY(attempt_id, partition_id, generation) REFERENCES attempts (id, partition_id, generation) ON DELETE RESTRICT,
	CONSTRAINT uq_artifacts_attempt_id UNIQUE (attempt_id),
	CONSTRAINT uq_artifacts_id_attempt_id_partition_id_generation UNIQUE (id, attempt_id, partition_id, generation),
	CONSTRAINT uq_artifacts_bucket_object_key UNIQUE (bucket, object_key),
	CONSTRAINT uq_artifacts_bucket_object_key_object_version UNIQUE (bucket, object_key, object_version),
	CONSTRAINT ck_artifacts_bounds CHECK (generation > 0 AND expected_size_bytes BETWEEN 0 AND 268435456 AND (verified_size_bytes IS NULL OR verified_size_bytes >= 0)),
	CONSTRAINT ck_artifacts_status CHECK (status IN ('RESERVED','VERIFIED','REJECTED')),
	CONSTRAINT ck_artifacts_verified CHECK (status <> 'VERIFIED' OR (object_version IS NOT NULL AND length(object_version) > 0 AND verified_sha256 IS NOT NULL AND verified_size_bytes IS NOT NULL AND verified_schema_hash IS NOT NULL AND verified_at IS NOT NULL AND verified_sha256 = expected_sha256 AND verified_size_bytes = expected_size_bytes AND verified_schema_hash = expected_schema_hash)),
	CONSTRAINT ck_artifacts_expected_sha256_format CHECK (expected_sha256 ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_artifacts_expected_schema_hash_format CHECK (expected_schema_hash ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_artifacts_reservation_fingerprint_format CHECK (reservation_fingerprint ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_artifacts_verified_sha256_format CHECK (verified_sha256 ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_artifacts_verified_schema_hash_format CHECK (verified_schema_hash ~ '^[0-9a-f]{64}$')
);

CREATE TABLE events (
	job_id UUID NOT NULL,
	seq BIGINT NOT NULL,
	partition_id UUID,
	attempt_id UUID,
	attempt_partition_id UUID,
	attempt_generation BIGINT,
	type TEXT NOT NULL,
	occurred_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	request_id TEXT,
	actor_type TEXT NOT NULL,
	actor_id TEXT NOT NULL,
	from_state TEXT,
	to_state TEXT,
	details JSONB NOT NULL,
	CONSTRAINT pk_events PRIMARY KEY (job_id, seq),
	CONSTRAINT fk_events_partition_id_partitions FOREIGN KEY(partition_id, job_id) REFERENCES partitions (id, job_id) ON DELETE RESTRICT,
	CONSTRAINT fk_events_attempt_id_attempts FOREIGN KEY(attempt_id, attempt_partition_id, attempt_generation) REFERENCES attempts (id, partition_id, generation) MATCH FULL ON DELETE RESTRICT,
	CONSTRAINT ck_events_sequence CHECK (seq > 0),
	CONSTRAINT ck_events_attempt_optional CHECK (num_nonnulls(attempt_id, attempt_partition_id, attempt_generation) IN (0,3)),
	CONSTRAINT ck_events_attempt_partition CHECK (attempt_id IS NULL OR (partition_id IS NOT NULL AND attempt_partition_id = partition_id)),
	CONSTRAINT fk_events_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE RESTRICT
);

CREATE TABLE request_receipts (
	scope TEXT NOT NULL,
	key VARCHAR(128) NOT NULL,
	request_hash TEXT NOT NULL,
	operation TEXT NOT NULL,
	job_id UUID,
	worker_session_id UUID,
	attempt_id UUID,
	status_code INTEGER NOT NULL,
	response JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	CONSTRAINT pk_request_receipts PRIMARY KEY (scope, key),
	CONSTRAINT ck_request_receipts_key CHECK (length(key) BETWEEN 1 AND 128 AND length(scope) > 0),
	CONSTRAINT ck_request_receipts_status_code CHECK (status_code BETWEEN 100 AND 599),
	CONSTRAINT ck_request_receipts_request_hash_format CHECK (request_hash ~ '^[0-9a-f]{64}$'),
	CONSTRAINT fk_request_receipts_job_id_jobs FOREIGN KEY(job_id) REFERENCES jobs (id) ON DELETE RESTRICT,
	CONSTRAINT fk_request_receipts_worker_session_id_workers FOREIGN KEY(worker_session_id) REFERENCES workers (session_id) ON DELETE RESTRICT,
	CONSTRAINT fk_request_receipts_attempt_id_attempts FOREIGN KEY(attempt_id) REFERENCES attempts (id) ON DELETE RESTRICT
);

CREATE TABLE accepted_results (
	partition_id UUID NOT NULL,
	attempt_id UUID NOT NULL,
	generation BIGINT NOT NULL,
	artifact_id UUID NOT NULL,
	accepted_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
	publication_fingerprint TEXT NOT NULL,
	CONSTRAINT pk_accepted_results PRIMARY KEY (partition_id),
	CONSTRAINT uq_accepted_results_artifact_id UNIQUE (artifact_id),
	CONSTRAINT uq_accepted_results_attempt_id UNIQUE (attempt_id),
	CONSTRAINT fk_accepted_results_attempt_id_attempts FOREIGN KEY(attempt_id, partition_id, generation) REFERENCES attempts (id, partition_id, generation) ON DELETE RESTRICT,
	CONSTRAINT fk_accepted_results_artifact_id_artifacts FOREIGN KEY(artifact_id, attempt_id, partition_id, generation) REFERENCES artifacts (id, attempt_id, partition_id, generation) ON DELETE RESTRICT,
	CONSTRAINT ck_accepted_results_generation CHECK (generation > 0),
	CONSTRAINT ck_accepted_results_publication_fingerprint_format CHECK (publication_fingerprint ~ '^[0-9a-f]{64}$'),
	CONSTRAINT fk_accepted_results_partition_id_partitions FOREIGN KEY(partition_id) REFERENCES partitions (id) ON DELETE RESTRICT
);

ALTER TABLE partitions ADD CONSTRAINT fk_partitions_latest_attempt FOREIGN KEY(id, latest_generation_fk) REFERENCES attempts (partition_id, generation) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX ix_input_artifacts_reconciliation ON input_artifacts (status, created_at);

CREATE INDEX ix_jobs_active_fair ON jobs (fair_ticket, created_at, id) WHERE status IN ('QUEUED', 'RUNNING');

CREATE INDEX ix_workers_liveness ON workers (last_seen_at) WHERE state != 'STOPPED';

CREATE INDEX ix_partitions_job_status ON partitions (job_id, status);

CREATE INDEX ix_partitions_ready ON partitions (job_id, eligible_at, ordinal) WHERE status = 'READY';

CREATE INDEX ix_worker_events_cursor ON worker_events (session_id, occurred_at);

CREATE INDEX ix_attempts_expiry ON attempts (lease_expires_at, partition_id) WHERE status = 'ACTIVE';

CREATE UNIQUE INDEX uq_attempts_active_partition ON attempts (partition_id) WHERE status = 'ACTIVE';

CREATE UNIQUE INDEX uq_attempts_active_worker ON attempts (worker_session_id) WHERE status = 'ACTIVE';

CREATE INDEX ix_artifacts_reconciliation ON artifacts (status, created_at);

CREATE INDEX ix_events_cursor ON events (job_id, partition_id, seq);

CREATE INDEX ix_request_receipts_job ON request_receipts (job_id);

CREATE INDEX ix_request_receipts_worker ON request_receipts (worker_session_id, created_at);
