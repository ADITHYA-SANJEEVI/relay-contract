"""Explicit immutable wire contracts, independent of persistence rows."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from relay.api.models import Hash, Policy, Sequence, Workload, Parameters

JobState = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
PartitionState = Literal["READY", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
AttemptState = Literal["ACTIVE", "EXPIRED", "FAILED", "SUCCEEDED", "CANCELLED"]
WorkerState = Literal["REGISTERED", "DRAINING", "STOPPED"]


class ReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Observation(ReadModel):
    as_of: datetime
    snapshot_scope: Literal["request_repeatable_read"] = "request_repeatable_read"


class AcceptedResult(ReadModel):
    partition_id: UUID
    attempt_id: UUID
    generation: Sequence
    artifact_id: UUID
    accepted_at: datetime
    publication_fingerprint: Hash


class AcceptedAuthority(ReadModel):
    status: Literal["ACCEPTED"] = "ACCEPTED"
    result: AcceptedResult


class NoAuthority(ReadModel):
    status: Literal["NONE"] = "NONE"


Authority = Annotated[AcceptedAuthority | NoAuthority, Field(discriminator="status")]


class ArtifactMetadata(ReadModel):
    id: UUID
    attempt_id: UUID
    partition_id: UUID
    generation: Sequence
    status: Literal["RESERVED", "VERIFIED", "REJECTED"]
    expected_sha256: Hash
    expected_size_bytes: Sequence
    expected_schema_hash: Hash
    bucket: str
    object_key: str
    object_version: str | None
    verified_sha256: Hash | None
    verified_size_bytes: Sequence | None
    verified_schema_hash: Hash | None
    created_at: datetime
    verified_at: datetime | None
    rejection_code: str | None
    content_verification: Literal["NOT_REQUESTED"] = "NOT_REQUESTED"


class AttemptObservation(ReadModel):
    id: UUID
    job_id: UUID
    partition_id: UUID
    ordinal: int
    generation: Sequence
    current_generation: Sequence
    worker_session_id: UUID
    status: AttemptState
    claimed_at: datetime
    lease_expires_at: datetime
    hard_deadline_at: datetime
    last_renew_seq: Sequence
    finished_at: datetime | None
    failure_code: str | None
    ownership_observation: Literal["WITHIN_DEADLINES", "DEADLINE_PASSED", "SUPERSEDED", "TERMINAL"]
    artifact: ArtifactMetadata | None
    accepted_authority: Authority
    is_accepted_attempt: bool
    events_url: str


class PartitionObservation(ReadModel):
    id: UUID
    job_id: UUID
    ordinal: int
    status: PartitionState
    generation: Sequence
    eligible_at: datetime
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    last_error_code: str | None
    latest_attempt: AttemptObservation | None
    accepted_authority: Authority


class PartitionSnapshot(Observation):
    partition: PartitionObservation
    attempts: tuple[AttemptObservation, ...]
    history_complete: Literal[True] = True


class PartitionPage(Observation):
    job_id: UUID
    items: tuple[PartitionObservation, ...]
    next_cursor: int | None


class AttemptSnapshot(Observation):
    attempt: AttemptObservation


class ArtifactSnapshot(Observation):
    job_id: UUID
    ordinal: int
    artifact: ArtifactMetadata
    accepted_authority: Authority
    is_accepted_artifact: bool


class PartitionCounts(ReadModel):
    READY: Sequence
    RUNNING: Sequence
    SUCCEEDED: Sequence
    FAILED: Sequence
    CANCELLED: Sequence


class JobSummary(ReadModel):
    id: UUID
    definition_hash: Hash
    workload_name: str
    workload_version: str
    status: JobState
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    partition_count: Sequence
    attempt_count: Sequence
    partition_counts: PartitionCounts
    next_event_seq: Sequence
    partial_result_count: Sequence
    complete: bool


class JobPage(Observation):
    items: tuple[JobSummary, ...]
    next_cursor: str | None


class JobSnapshot(Observation):
    job: JobSummary


class ResultManifest(ReadModel):
    ordinal: int
    authority: AcceptedAuthority
    artifact: ArtifactMetadata
    content_url: str
    verification_url: str


class ResultPage(Observation):
    job_id: UUID
    job_status: JobState
    complete: bool
    partition_count: Sequence
    partial_result_count: Sequence
    items: tuple[ResultManifest, ...]
    next_cursor: int | None


class DiagnosticDetails(ReadModel):
    state: Literal["SANITIZED", "MALFORMED"]
    values: dict[str, str | None]
    omitted: bool


class EventObservation(ReadModel):
    job_id: UUID
    seq: Sequence
    partition_id: UUID | None
    attempt_id: UUID | None
    attempt_generation: Sequence | None
    type: str
    occurred_at: datetime
    request_id: str | None
    actor_type: str
    actor_id: str
    from_state: str | None
    to_state: str | None
    details: DiagnosticDetails


class EventPage(Observation):
    job_id: UUID
    direction: Literal["forward", "backward"]
    partition_id: UUID | None
    attempt_id: UUID | None
    items: tuple[EventObservation, ...]
    loaded_from_seq: Sequence | None
    loaded_through_seq: Sequence | None
    frontier_seq: Sequence
    has_more: bool
    next_cursor: Sequence | None


class WorkerObservation(ReadModel):
    session_id: UUID
    display_name: str
    state: WorkerState
    deployment_workload_digest: str
    created_at: datetime
    last_seen_at: datetime
    stopped_at: datetime | None
    last_heartbeat_seq: Sequence
    liveness: Literal["FRESH", "SUSPECT", "NOT_APPLICABLE"]
    current_attempt: AttemptObservation | None


class WorkerPage(Observation):
    items: tuple[WorkerObservation, ...]
    next_cursor: UUID | None


class WorkerSnapshot(Observation):
    worker: WorkerObservation


class ParticipationPage(Observation):
    session_id: UUID
    items: tuple[AttemptObservation, ...]
    next_cursor: UUID | None


class WorkerEvent(ReadModel):
    session_id: UUID
    seq: Sequence
    type: str
    occurred_at: datetime
    request_id: str | None
    details: DiagnosticDetails


class WorkerEventPage(Observation):
    session_id: UUID
    items: tuple[WorkerEvent, ...]
    loaded_from_seq: Sequence | None
    loaded_through_seq: Sequence | None
    frontier_seq: Sequence
    has_more: bool
    next_cursor: Sequence | None


class InputMetadata(ReadModel):
    input_ordinal: int
    artifact_id: UUID
    object_version: str
    sha256: Hash
    size_bytes: Sequence
    schema_hash: Hash
    row_count: Sequence


class InputSlice(ReadModel):
    slice_ordinal: int
    input_ordinal: int
    first_row: Sequence
    row_count: Sequence


class DefinitionPartition(ReadModel):
    partition_id: UUID
    ordinal: int
    slices: tuple[InputSlice, ...]


class DefinitionSnapshot(Observation):
    job_id: UUID
    version: int
    parent_job_id: UUID | None
    definition_hash: Hash
    manifest_hash: Hash
    workload: Workload
    parameters: Parameters
    policy: Policy
    inputs: tuple[InputMetadata, ...]
    partitions: tuple[DefinitionPartition, ...]
    scope: Literal["complete_immutable_definition"] = "complete_immutable_definition"


class VerificationResult(ReadModel):
    state: Literal["VERIFIED", "FAILED"]
    code: Literal["verified", "storage_missing", "storage_unavailable", "version_unavailable",
                  "checksum_mismatch", "size_mismatch", "content_invalid", "transport_read_failure"]
    checked_at: datetime
    object_version: str
    sha256: Hash
    size_bytes: Sequence


class VerificationSnapshot(ArtifactSnapshot):
    verification: VerificationResult


class CapabilityState(ReadModel):
    id: str
    state: Literal["AVAILABLE", "UNAVAILABLE", "DEFERRED", "UNSUPPORTED"]
    routes: tuple[str, ...]
    reason: str | None = None


class Capabilities(Observation):
    api_revision: Literal["r1_operator_visibility_v1"] = "r1_operator_visibility_v1"
    database_revision: str
    authentication: Literal["existing_local_operator_bearer"] = "existing_local_operator_bearer"
    capabilities: tuple[CapabilityState, ...]
