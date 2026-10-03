"""GET-only operator routes protected by the existing local operator credential."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from relay.control.common import Rejection

from . import models as m


def router(reads, authenticate):
    def operator(request: Request):
        authenticate(request)
        # Unknown query fields cannot become accidental storage/SQL selectors.
        allowed = {field.alias for field in request.scope["route"].dependant.query_params}
        if set(request.query_params) - allowed:
            raise Rejection("invalid_request", 422)

    routes = APIRouter(prefix="/v1/operator", dependencies=[Depends(operator)], tags=["operator"])

    @routes.get("/capabilities", response_model=m.Capabilities)
    def capabilities():
        return reads.capabilities()

    @routes.get("/jobs", response_model=m.JobPage)
    def jobs(cursor: str | None = Query(None, max_length=512), limit: int = Query(100, ge=1, le=500),
             status: m.JobState | None = None):
        return reads.jobs(cursor, limit, status)

    @routes.get("/jobs/{identity}", response_model=m.JobSnapshot)
    def job(identity: UUID):
        return reads.job(identity)

    @routes.get("/jobs/{identity}/partitions", response_model=m.PartitionPage)
    def partitions(identity: UUID, after_ordinal: int = Query(-1, ge=-1, le=4095),
                   limit: int = Query(100, ge=1, le=500), status: m.PartitionState | None = None):
        return reads.partitions(identity, after_ordinal, limit, status)

    @routes.get("/partitions/{identity}", response_model=m.PartitionSnapshot)
    @routes.get("/partitions/{identity}/history", response_model=m.PartitionSnapshot)
    def partition(identity: UUID):
        return reads.partition(identity)

    @routes.get("/attempts/{identity}", response_model=m.AttemptSnapshot)
    def attempt(identity: UUID):
        return reads.attempt(identity)

    @routes.get("/artifacts/{identity}", response_model=m.ArtifactSnapshot)
    def artifact(identity: UUID):
        return reads.artifact(identity)

    @routes.get("/artifacts/{identity}/verification", response_model=m.VerificationSnapshot)
    def verification(identity: UUID):
        return reads.verification(identity)

    @routes.get("/jobs/{identity}/result-metadata", response_model=m.ResultPage)
    def results(identity: UUID, after_ordinal: int = Query(-1, ge=-1, le=4095),
                limit: int = Query(100, ge=1, le=500)):
        return reads.results(identity, after_ordinal, limit)

    @routes.get("/jobs/{identity}/events", response_model=m.EventPage)
    def events(identity: UUID, after_seq: str | None = Query(None, max_length=19),
               before_seq: str | None = Query(None, max_length=19),
               direction: Literal["forward", "backward"] = "forward", limit: int = Query(100, ge=1, le=500),
               partition_id: UUID | None = None, attempt_id: UUID | None = None):
        return reads.events(identity, after_seq, before_seq, direction, limit, partition_id, attempt_id)

    @routes.get("/workers", response_model=m.WorkerPage)
    def workers(after_session: UUID | None = None, limit: int = Query(100, ge=1, le=500),
                state: m.WorkerState | None = None):
        return reads.workers(after_session, limit, state)

    @routes.get("/workers/{identity}", response_model=m.WorkerSnapshot)
    def worker(identity: UUID):
        return reads.worker(identity)

    @routes.get("/workers/{identity}/attempts", response_model=m.ParticipationPage)
    def participation(identity: UUID, after_attempt: UUID | None = None, limit: int = Query(100, ge=1, le=500)):
        return reads.participation(identity, after_attempt, limit)

    @routes.get("/workers/{identity}/events", response_model=m.WorkerEventPage)
    def worker_events(identity: UUID, after_seq: str = Query("0", max_length=19),
                      limit: int = Query(100, ge=1, le=500)):
        return reads.worker_events(identity, after_seq, limit)

    @routes.get("/jobs/{identity}/definition", response_model=m.DefinitionSnapshot)
    def definition(identity: UUID):
        return reads.definition(identity)

    return routes
