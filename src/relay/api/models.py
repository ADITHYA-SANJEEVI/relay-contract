from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Counter = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,18})$")]
Ordinal = Annotated[StrictInt, Field(ge=0, le=4095)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputReservation(ContractModel):
    sha256: Hash
    size_bytes: Annotated[Counter, Field(description="Decimal bigint string")]
    media_type: Literal["application/vnd.apache.parquet"]
    schema_hash: Hash


class Workload(ContractModel):
    name: Literal["normalize_aggregate"]
    version: Literal["1"]
    digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class Parameters(ContractModel):
    normalization_version: Literal["1"] = "1"


class Policy(ContractModel):
    max_attempts: Annotated[StrictInt, Field(ge=1, le=10)] = 5
    lease_seconds: Annotated[StrictInt, Field(ge=1, le=3600)] = 30
    max_attempt_seconds: Annotated[StrictInt, Field(ge=60, le=3600)] = 600


class InputReference(ContractModel):
    input_ordinal: Ordinal
    artifact_id: UUID


class Slice(ContractModel):
    input_ordinal: Ordinal
    first_row: Counter
    row_count: Counter


class Partition(ContractModel):
    ordinal: Ordinal
    slices: Annotated[list[Slice], Field(min_length=1)]


class Submission(ContractModel):
    workload: Workload
    inputs: Annotated[list[InputReference], Field(min_length=1, max_length=4096)]
    partitions: Annotated[list[Partition], Field(min_length=1, max_length=4096)]
    parameters: Parameters = Field(default_factory=Parameters)
    policy: Policy = Field(default_factory=Policy)
    parent_job_id: UUID | None = None


class Registration(ContractModel):
    session_id: UUID
    session_secret: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    display_name: Annotated[str, Field(min_length=1, max_length=128)]
    deployment_workload_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class Claim(ContractModel):
    pass


class ArtifactReservation(ContractModel):
    job_id: UUID
    partition_id: UUID
    generation: Counter
    sha256: Hash
    size_bytes: Counter
    schema_hash: Hash


class Completion(ContractModel):
    request_id: Annotated[str, Field(min_length=1, max_length=128)]
    job_id: UUID
    partition_id: UUID
    generation: Counter
    artifact_id: UUID
    artifact_uri: Annotated[str, Field(min_length=1, max_length=2048)]
    sha256: Hash
