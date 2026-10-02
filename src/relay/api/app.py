"""Relay HTTP surface. Success responses follow transaction commit."""

import hashlib
import json
import logging
import secrets
from contextlib import asynccontextmanager
from tempfile import SpooledTemporaryFile
from uuid import UUID, uuid4

import sqlalchemy as sa
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from relay.artifacts.gateway import Gateway
from relay.config import load_settings
from relay.control.common import Rejection, one, wire
from relay.control.service import Control, artifact_response, input_response
from relay.control.publication import accepted_response
from relay.db import schema as db
from relay.db.connection import database_url, make_engine

from .models import ArtifactReservation, Claim, Completion, InputReservation, Registration, Submission

logger = logging.getLogger("relay.api")


def create_app(settings):
    engine = make_engine(database_url(settings))
    control = Control(engine, settings)
    gateway = Gateway(engine, settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        gateway.store.close(); engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.state.engine, app.state.control, app.state.gateway = engine, control, gateway

    @app.middleware("http")
    async def request_context(request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        logger.info(json.dumps({"component": "api", "operation": request.method,
                    "request_id": request.state.request_id, "status": response.status_code}))
        return response

    def error_response(request, code, status, outcome="rejected"):
        return JSONResponse(status_code=status, content={"error": dict(code=code, message=code,
            retryable=status == 503, outcome=outcome, request_id=getattr(request.state, "request_id", None), details={})})

    @app.exception_handler(Rejection)
    async def reject(request, error):
        return error_response(request, error.code, error.status,
                              "unknown" if error.status == 503 else "rejected")

    @app.exception_handler(RequestValidationError)
    async def invalid_path(request, error):
        return error_response(request, "invalid_request", 422)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
        # A disconnect at COMMIT can have unknown outcome. Never infer rollback.
        state = getattr(getattr(error, "orig", None), "sqlstate", None)
        known_abort = isinstance(error, DBAPIError) and not error.connection_invalidated and state in (
            "23503", "23505", "23514", "40001", "40P01", "55P03", "57014")
        return error_response(request, "database_unavailable", 503, "not_committed" if known_abort else "unknown")

    @app.exception_handler(Exception)
    async def unexpected(request, error):
        logger.error(json.dumps({"component": "api", "error_code": "internal_error",
                     "error_type": type(error).__name__, "request_id": getattr(request.state, "request_id", None)}))
        return error_response(request, "internal_error", 500, "unknown")

    def operator(request):
        token = request.headers.get("Authorization", "")
        if not secrets.compare_digest(token.encode(), ("Bearer " + settings["RELAY_OPERATOR_TOKEN"]).encode()):
            raise Rejection("unauthenticated", 401)

    def worker(request):
        try: identity = UUID(request.headers.get("X-Worker-Session", ""))
        except ValueError: raise Rejection("unauthenticated", 401)
        token = request.headers.get("Authorization", "")
        if not token.startswith("Bearer "): raise Rejection("unauthenticated", 401)
        return control.authenticate_worker(identity, token[7:])

    def key(request):
        value = request.headers.get("Idempotency-Key", "")
        if not 1 <= len(value) <= 128: raise Rejection("invalid_idempotency_key", 400)
        return value

    async def model_body(request, model):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 1048576: raise Rejection("descriptor_too_large", 422)
        try: return model.model_validate_json(bytes(content))
        except (ValidationError, ValueError): raise Rejection("invalid_request", 422)

    async def upload_body(request, identity, is_input):
        maximum = int(settings.get("RELAY_MAX_INPUT_BYTES", 268435456)) if is_input else 268435456
        digest, count = hashlib.sha256(), 0
        with SpooledTemporaryFile(max_size=8 * 1024 * 1024) as file:
            async for chunk in request.stream():
                count += len(chunk)
                if count > maximum: raise Rejection("content_too_large", 422)
                digest.update(chunk); file.write(chunk)
            file.seek(0)
            return await run_in_threadpool(gateway.upload, identity, file, digest.hexdigest(), count, is_input=is_input)

    @app.get("/health/live")
    def live(): return {"live": True}

    @app.get("/health/ready")
    def ready():
        try:
            with engine.connect() as c:
                if c.scalar(sa.text("SELECT version_num FROM relay_schema_version")) != "0002_readiness":
                    raise Rejection("schema_not_ready", 503)
            gateway.ready()
        except Rejection: raise
        except Exception: raise Rejection("dependencies_not_ready", 503)
        return {"ready": True, "migration_revision": "0002_readiness"}

    @app.post("/v1/inputs")
    async def reserve_input(request: Request):
        operator(request)
        model = await model_body(request, InputReservation)
        status, response = await run_in_threadpool(control.reserve_input, key(request), model)
        return JSONResponse(status_code=status, content=response)

    @app.put("/v1/inputs/{identity}/content")
    async def upload_input(identity: UUID, request: Request):
        operator(request)
        return await upload_body(request, identity, True)

    @app.get("/v1/inputs/{identity}")
    def get_input(identity: UUID, request: Request):
        operator(request)
        return input_response(gateway.snapshot(db.input_artifacts, identity))

    @app.post("/v1/jobs")
    async def submit(request: Request):
        operator(request)
        model = await model_body(request, Submission)
        status, response = await run_in_threadpool(control.submit, key(request), model)
        return JSONResponse(status_code=status, content=response)

    @app.get("/v1/jobs/{identity}")
    def get_job(identity: UUID, request: Request):
        operator(request)
        # One SQL statement snapshot for identity and all counts.
        p, a, r = db.partitions, db.attempts, db.accepted_results
        statement = sa.select(db.jobs, sa.select(sa.func.count()).where(p.c.job_id == db.jobs.c.id).scalar_subquery().label("partitions"),
            sa.select(sa.func.count()).select_from(a.join(p, p.c.id == a.c.partition_id)).where(p.c.job_id == db.jobs.c.id).scalar_subquery().label("attempts"),
            sa.select(sa.func.count()).select_from(r.join(p, p.c.id == r.c.partition_id)).where(p.c.job_id == db.jobs.c.id).scalar_subquery().label("accepted"),
            *[sa.select(sa.func.count()).where(p.c.job_id == db.jobs.c.id, p.c.status == state).scalar_subquery().label("count_" + state)
              for state in ("READY", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED")]).where(db.jobs.c.id == identity)
        with engine.connect() as c:
            row = c.execute(statement).mappings().first()
        if not row: raise Rejection("not_found", 404)
        return wire({k: row[k] for k in ("id", "definition_hash", "status", "created_at", "started_at", "finished_at")} | {
            "partition_count": str(row["partitions"]), "attempt_count": str(row["attempts"]),
            "partition_counts": {s: str(row["count_" + s]) for s in ("READY", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED")},
            "next_event_seq": str(row["next_event_seq"]), "partial_result_count": str(row["accepted"]), "complete": row["status"] == "SUCCEEDED"})

    @app.get("/v1/jobs/{identity}/partitions")
    def get_partitions(identity: UUID, request: Request, after_ordinal: int = Query(-1, ge=-1),
                       limit: int = Query(100, ge=1, le=500), status: str | None = None):
        operator(request)
        if status is not None and status not in ("READY", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"):
            raise Rejection("invalid_request", 422)
        p, a, r = db.partitions, db.attempts, db.accepted_results
        statement = sa.select(p.c.id, p.c.ordinal, p.c.status, p.c.generation, p.c.eligible_at, p.c.last_error_code,
            a.c.id.label("attempt_id"), a.c.lease_expires_at, a.c.hard_deadline_at, r.c.artifact_id.label("accepted_artifact_id"))
        statement = statement.select_from(p.outerjoin(a, sa.and_(a.c.partition_id == p.c.id, a.c.generation == p.c.latest_generation_fk))
            .outerjoin(r, r.c.partition_id == p.c.id)).where(p.c.job_id == identity, p.c.ordinal > after_ordinal)
        if status: statement = statement.where(p.c.status == status)
        with engine.connect() as c:
            one(c, db.jobs, db.jobs.c.id == identity)
            rows = c.execute(statement.order_by(p.c.ordinal).limit(limit + 1)).mappings().all()
        return wire({"items": [dict(row) | {"generation": str(row["generation"])} for row in rows[:limit]],
                     "next_cursor": rows[limit - 1]["ordinal"] if len(rows) > limit else None})

    @app.get("/v1/jobs/{identity}/events")
    def get_events(identity: UUID, request: Request, after_seq: str = "0", limit: int = Query(100, ge=1, le=500)):
        operator(request)
        if not after_seq.isdecimal() or len(after_seq) > 19: raise Rejection("invalid_request", 422)
        with engine.connect() as c:
            one(c, db.jobs, db.jobs.c.id == identity)
            rows = c.execute(sa.select(db.events).where(db.events.c.job_id == identity, db.events.c.seq > int(after_seq))
                             .order_by(db.events.c.seq).limit(limit + 1)).mappings().all()
        return wire({"items": [dict(row) | {"seq": str(row["seq"]), "attempt_generation": None if row["attempt_generation"] is None
            else str(row["attempt_generation"])} for row in rows[:limit]],
            "next_cursor": str(rows[limit - 1]["seq"]) if len(rows) > limit else None})

    @app.get("/v1/jobs/{identity}/results")
    def get_results(identity: UUID, request: Request, after_ordinal: int = Query(-1, ge=-1),
                    limit: int = Query(100, ge=1, le=500)):
        operator(request)
        p, r, f = db.partitions, db.accepted_results, db.artifacts
        # Read-only snapshot covers status, count and this ordinal page. No store
        # I/O until the transaction and connection have both closed.
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            with c.begin():
                c.execute(sa.text("SET TRANSACTION READ ONLY"))
                job = one(c, db.jobs, db.jobs.c.id == identity)
                count = c.scalar(sa.select(sa.func.count()).select_from(r.join(p, p.c.id == r.c.partition_id))
                                 .where(p.c.job_id == identity))
                rows = c.execute(sa.select(r, p.c.ordinal)
                    .select_from(r.join(p, p.c.id == r.c.partition_id).join(f, f.c.id == r.c.artifact_id))
                    .where(p.c.job_id == identity, p.c.ordinal > after_ordinal)
                    .order_by(p.c.ordinal).limit(limit + 1)).mappings().all()
                artifacts = {row["id"]: dict(row) for row in c.execute(sa.select(f).where(
                    f.c.id.in_([row["artifact_id"] for row in rows[:limit]]))).mappings()}
        items = []
        for row in rows[:limit]:
            artifact = artifacts[row["artifact_id"]]
            with gateway.verified_result(artifact):
                pass  # Integrity checked against this exact immutable version.
            items.append(accepted_response(row, artifact) | {"ordinal": row["ordinal"],
                         "content_url": f"/v1/artifacts/{row['artifact_id']}/content"})
        return wire({"job_id": identity, "job_status": job["status"], "complete": job["status"] == "SUCCEEDED",
            "partial_result_count": str(count), "partition_count": str(job["partition_count"]), "items": items,
            "next_cursor": rows[limit - 1]["ordinal"] if len(rows) > limit else None})

    @app.post("/v1/workers/register")
    async def register(request: Request):
        if not secrets.compare_digest(request.headers.get("Authorization", "").encode(), ("Bearer " + settings["RELAY_WORKER_BOOTSTRAP_TOKEN"]).encode()):
            raise Rejection("unauthenticated", 401)
        model = await model_body(request, Registration)
        status, response = await run_in_threadpool(control.register, model)
        return JSONResponse(status_code=status, content=response)

    @app.post("/v1/workers/{session}/claim")
    async def claim(session: UUID, request: Request):
        identity = await run_in_threadpool(worker, request)
        if identity != session: raise Rejection("wrong_owner", 403)
        await model_body(request, Claim)
        status, response = await run_in_threadpool(control.claim, identity, key(request))
        return Response(status_code=204) if status == 204 else JSONResponse(status_code=status, content=response)

    @app.get("/v1/attempts/{identity}")
    def get_attempt(identity: UUID, request: Request):
        session = worker(request)
        with engine.connect() as c:
            row = one(c, db.attempts, db.attempts.c.id == identity)
            if row["worker_session_id"] != session: raise Rejection("wrong_owner", 403)
            artifact = c.execute(sa.select(db.artifacts).where(db.artifacts.c.attempt_id == identity)).mappings().first()
            accepted = c.execute(sa.select(db.accepted_results).where(db.accepted_results.c.attempt_id == identity)).mappings().first()
            partition = one(c, db.partitions, db.partitions.c.id == row["partition_id"])
            job = one(c, db.jobs, db.jobs.c.id == partition["job_id"])
            t = c.scalar(sa.select(sa.func.clock_timestamp()))
        return wire({k: row[k] for k in ("id", "partition_id", "worker_session_id", "status", "claimed_at", "lease_expires_at", "hard_deadline_at")} | {
            "generation": str(row["generation"]), "current_generation": str(partition["generation"]), "db_time": t,
            "job_status": job["status"], "partition_status": partition["status"],
            "artifact": artifact_response(artifact) if artifact else None,
            "accepted_result": accepted_response(accepted, artifact) if accepted else None})

    @app.get("/v1/attempts/{identity}/inputs/{ordinal}/content")
    def download_slice(identity: UUID, ordinal: int, request: Request):
        session = worker(request)
        file = gateway.assigned_slice(identity, ordinal, session)
        def chunks():
            with file:
                while chunk := file.read(1024 * 1024): yield chunk
        return StreamingResponse(chunks(), media_type="application/vnd.apache.parquet")

    @app.post("/v1/attempts/{identity}/artifact")
    async def reserve_artifact(identity: UUID, request: Request):
        session = await run_in_threadpool(worker, request)
        model = await model_body(request, ArtifactReservation)
        status, response = await run_in_threadpool(control.reserve_artifact, session, identity, model)
        return JSONResponse(status_code=status, content=response)

    @app.post("/v1/attempts/{identity}/complete")
    async def complete(identity: UUID, request: Request):
        session = await run_in_threadpool(worker, request)
        model = await model_body(request, Completion)
        status, response = await run_in_threadpool(control.complete, session, identity, model)
        return JSONResponse(status_code=status, content=response)

    @app.get("/v1/artifacts/{identity}/content")
    def accepted_content(identity: UUID, request: Request):
        token = request.headers.get("Authorization", "")
        is_operator = secrets.compare_digest(token.encode(), ("Bearer " + settings["RELAY_OPERATOR_TOKEN"]).encode())
        session = None if is_operator else worker(request)
        with engine.connect() as c:
            if is_operator:
                one(c, db.accepted_results, db.accepted_results.c.artifact_id == identity)
            artifact = one(c, db.artifacts, db.artifacts.c.id == identity)
            if not is_operator:
                attempt = one(c, db.attempts, db.attempts.c.id == artifact["attempt_id"])
                if attempt["worker_session_id"] != session: raise Rejection("wrong_owner", 403)
                if artifact["status"] != "VERIFIED": raise Rejection("artifact_not_verified")
        file = gateway.verified_result(artifact)
        def chunks():
            with file:
                while chunk := file.read(1024 * 1024): yield chunk
        return StreamingResponse(chunks(), media_type="application/vnd.apache.parquet",
            headers={"X-SHA256": artifact["verified_sha256"], "X-Object-Version": artifact["object_version"]})

    @app.put("/v1/artifacts/{identity}/content")
    async def upload_artifact(identity: UUID, request: Request):
        session = await run_in_threadpool(worker, request)
        row = await run_in_threadpool(gateway.snapshot, db.artifacts, identity)
        with engine.connect() as c:
            attempt = one(c, db.attempts, db.attempts.c.id == row["attempt_id"])
        if attempt["worker_session_id"] != session: raise Rejection("wrong_owner", 403)
        return await upload_body(request, identity, False)

    return app


def app_from_file(path):
    return create_app(load_settings(path))
