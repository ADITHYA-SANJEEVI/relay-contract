import asyncio
import io
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
import httpx
from botocore.exceptions import ClientError, EndpointConnectionError
from sqlalchemy.exc import DBAPIError

from relay.api.app import create_app
from relay.db import schema as db
from relay.operator.service import (OperatorReads, SCHEMA_REVISION, attempt_model,
    authority, job_query, attempt_query)
from relay.recovery.service import run_batch
from tests.faults.helpers import (advance_eligibility, fail_http, fresh_claim, new_job, new_owner, verify_output)
from tests.integration.conftest import claim, register
from tests.integration.test_m1b import row_for
from tests.publication.test_m1c import complete, prepared, shorten_lease


class LocalClient:
    """In-process HTTP over the real-service app; no deprecated TestClient dependency."""
    def __init__(self, app):
        self.app = app

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.app.state.gateway.store.close()
        self.app.state.engine.dispose()

    def get(self, path, **kwargs):
        async def request():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(self.app), base_url="http://relay.test") as client:
                return await client.get(path, **kwargs)
        return asyncio.run(request())


def get(api, path, **params):
    response = api.client.get("/v1/operator/" + path, headers=api.operator, params=params)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    data = response.json()
    assert datetime.fromisoformat(data["as_of"]).tzinfo is not None
    assert data["snapshot_scope"] == "request_repeatable_read"
    return data


def durable_state(api):
    with api.engine.connect().execution_options(isolation_level="REPEATABLE READ") as c:
        with c.begin():
            c.execute(sa.text("SET TRANSACTION READ ONLY"))
            return {table.name: sorted((json.dumps(dict(row), default=str, sort_keys=True)
                for row in c.execute(sa.select(table)).mappings())) for table in db.metadata.tables.values()}


def test_read_surface_authority_manifests_definition_and_no_mutation(api):
    claimed, owner, body = prepared(api)
    job, partition, attempt, output = (claimed["job_id"], claimed["partition_id"], claimed["attempt_id"], body["artifact_id"])
    none = get(api, f"partitions/{partition}")
    assert none["partition"]["accepted_authority"] == {"status": "NONE"}
    assert none["attempts"][0]["artifact"]["status"] == "VERIFIED"
    assert not none["attempts"][0]["is_accepted_attempt"]
    assert get(api, f"jobs/{job}/result-metadata")["items"] == []
    response = api.client.get(f"/v1/operator/artifacts/{output}/verification", headers=api.operator)
    assert response.status_code == 409 and response.json()["error"]["code"] == "accepted_content_unavailable"
    assert complete(api, claimed, owner, body).status_code == 201
    before = durable_state(api)
    for path in ("capabilities", "jobs", f"jobs/{job}", f"jobs/{job}/partitions", f"partitions/{partition}",
                 f"partitions/{partition}/history", f"attempts/{attempt}", f"artifacts/{output}",
                 f"jobs/{job}/result-metadata", f"jobs/{job}/events", f"jobs/{job}/definition", "workers",
                 f"workers/{claimed['worker_session_id']}", f"workers/{claimed['worker_session_id']}/attempts",
                 f"workers/{claimed['worker_session_id']}/events", f"artifacts/{output}/verification"):
        get(api, path)
    assert durable_state(api) == before
    accepted = get(api, f"partitions/{partition}")["partition"]["accepted_authority"]
    persisted = row_for(api, db.artifacts, output)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["result"]["artifact_id"] == output
    assert accepted["result"]["attempt_id"] == attempt
    assert accepted["result"]["generation"] == "1"
    assert datetime.fromisoformat(accepted["result"]["accepted_at"]) == datetime.fromisoformat(
        complete(api, claimed, owner, body).json()["accepted_result"]["accepted_at"])
    metadata = get(api, f"jobs/{job}/result-metadata")
    assert metadata["complete"] and metadata["partial_result_count"] == "1"
    assert metadata["items"][0]["authority"] == accepted
    assert metadata["items"][0]["artifact"]["content_verification"] == "NOT_REQUESTED"
    verification = get(api, f"artifacts/{output}/verification")
    assert verification["verification"]["state"] == "VERIFIED"
    assert verification["verification"]["object_version"] == persisted["object_version"]
    definition = get(api, f"jobs/{job}/definition")
    assert definition["scope"] == "complete_immutable_definition"
    assert definition["partitions"][0]["slices"][0]["row_count"] == "12"
    assert definition["workload"]["name"] == "normalize_aggregate"
    assert definition["inputs"][0]["object_version"]


def test_t04_g4_expired_verified_g5_accepted_stale_evidence(api):
    job, rows = new_job(api)
    first_owner = new_owner(api)
    for generation in range(1, 5):
        old = fresh_claim(api, first_owner, generation)
        if generation == 4:
            old_body, old_artifact = verify_output(api, old, first_owner, rows)
        shorten_lease(api, old, expired=True)
        # The read cannot settle an elapsed ACTIVE attempt.
        observed = get(api, f"attempts/{old['attempt_id']}")["attempt"]
        assert observed["status"] == "ACTIVE" and observed["ownership_observation"] == "DEADLINE_PASSED"
        assert run_batch(api.engine)[0]["outcome"] == "expired"
        advance_eligibility(api, old)
    next_owner = new_owner(api)
    current = fresh_claim(api, next_owner, 5)
    current_body, current_artifact = verify_output(api, current, next_owner, rows)
    assert complete(api, current, next_owner, current_body).status_code == 201
    rejection = complete(api, old, first_owner, old_body)
    assert rejection.status_code == 409 and rejection.json()["error"]["code"] == "stale_generation"
    assert complete(api, old, first_owner, old_body).json() == rejection.json()
    snapshot = get(api, f"partitions/{old['partition_id']}/history")
    assert snapshot["history_complete"]
    assert [a["generation"] for a in snapshot["attempts"]] == ["5", "4", "3", "2", "1"]
    assert [a["status"] for a in snapshot["attempts"]] == ["SUCCEEDED", "EXPIRED", "EXPIRED", "EXPIRED", "EXPIRED"]
    assert snapshot["attempts"][1]["artifact"]["id"] == old_artifact["id"]
    assert snapshot["attempts"][1]["artifact"]["status"] == "VERIFIED"
    assert not snapshot["attempts"][1]["is_accepted_attempt"]
    accepted = snapshot["partition"]["accepted_authority"]
    assert accepted["result"]["attempt_id"] == current["attempt_id"]
    assert accepted["result"]["artifact_id"] == current_artifact["id"]
    assert old_artifact["sha256"] == current_artifact["sha256"]
    assert old_artifact["id"] != current_artifact["id"]
    events = get(api, f"jobs/{job}/events", attempt_id=old["attempt_id"])
    rejects = [event for event in events["items"] if event["type"] == "PUBLICATION_REJECTED"]
    assert len(rejects) == 1
    assert rejects[0]["attempt_generation"] == "4" and rejects[0]["partition_id"] == old["partition_id"]
    assert rejects[0]["request_id"] == old_body["request_id"]
    assert rejects[0]["details"]["values"] == {"code": "stale_generation"}
    print("R1 T04", json.dumps(dict(job_id=job, history=[a["generation"] for a in snapshot["attempts"]],
        authority=accepted, rejection=rejects[0]), sort_keys=True))


def test_t09_bounded_retry_and_partial_failed_job(api):
    job, rows = new_job(api, maximum=3, partitions=2)
    owner = new_owner(api)
    for generation in range(1, 4):
        failed = fresh_claim(api, owner, generation)
        assert fail_http(api, failed, owner).status_code == 200
        if generation < 3:
            advance_eligibility(api, failed)
    assert get(api, f"jobs/{job}")["job"]["status"] == "RUNNING"
    assert get(api, f"partitions/{failed['partition_id']}")["partition"]["status"] == "FAILED"
    healthy = fresh_claim(api, owner, 1)
    body, _ = verify_output(api, healthy, owner, rows[12:])
    assert complete(api, healthy, owner, body).status_code == 201
    manifest = get(api, f"jobs/{job}/result-metadata")
    assert manifest["job_status"] == "FAILED" and not manifest["complete"]
    assert manifest["partial_result_count"] == "1" and manifest["partition_count"] == "2"
    history = get(api, f"partitions/{failed['partition_id']}")
    assert [a["generation"] for a in history["attempts"]] == ["3", "2", "1"]
    assert all(a["failure_code"] == "worker_crash" for a in history["attempts"])
    assert history["partition"]["accepted_authority"] == {"status": "NONE"}
    assert claim(api, owner).status_code == 204


def test_event_forward_backward_filters_and_frontiers(api):
    claimed, owner, body = prepared(api)
    assert complete(api, claimed, owner, body).status_code == 201
    path = f"jobs/{claimed['job_id']}/events"
    first = get(api, path, limit=2)
    assert first["has_more"] and first["loaded_from_seq"] == "1" and first["loaded_through_seq"] == "2"
    assert first["next_cursor"] == "2"
    collected, cursor = first["items"], first["next_cursor"]
    while cursor:
        page = get(api, path, after_seq=cursor, limit=2)
        collected.extend(page["items"])
        cursor = page["next_cursor"]
    assert [int(event["seq"]) for event in collected] == list(range(1, int(first["frontier_seq"]) + 1))
    backward, cursor = [], None
    while True:
        params = dict(direction="backward", limit=2)
        if cursor is not None:
            params["before_seq"] = cursor
        page = get(api, path, **params)
        assert page["items"] == sorted(page["items"], key=lambda e: int(e["seq"]))
        backward = page["items"] + backward
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert backward == collected
    filtered = get(api, path, attempt_id=claimed["attempt_id"], partition_id=claimed["partition_id"])
    assert all(e["attempt_id"] == claimed["attempt_id"] for e in filtered["items"])
    job_only = next(e for e in collected if e["type"] == "JOB_SUCCEEDED")
    assert job_only["attempt_id"] is None and job_only["partition_id"] is None
    empty = get(api, path, after_seq=first["frontier_seq"])
    assert empty["items"] == [] and empty["loaded_from_seq"] is None and empty["next_cursor"] is None


def test_worker_lifecycle_liveness_assignments_and_participation(api):
    claimed, owner, body = prepared(api)
    session = owner["X-Worker-Session"]
    worker = get(api, f"workers/{session}")["worker"]
    assert worker["state"] == "REGISTERED" and worker["liveness"] == "FRESH"
    assert worker["current_attempt"]["id"] == claimed["attempt_id"]
    with api.admin_engine.begin() as c:
        c.execute(db.workers.update().where(db.workers.c.session_id == UUID(session)).values(
            last_seen_at=sa.func.clock_timestamp() - sa.text("interval '31 seconds'")))
    shorten_lease(api, claimed, expired=True)
    suspect = get(api, f"workers/{session}")["worker"]
    assert suspect["state"] == "REGISTERED" and suspect["liveness"] == "SUSPECT"
    assert suspect["current_attempt"]["status"] == "ACTIVE"
    assert suspect["current_attempt"]["ownership_observation"] == "DEADLINE_PASSED"
    assert run_batch(api.engine)[0]["outcome"] == "expired"
    assert api.client.post(f"/v1/workers/{session}/drain", headers=owner, json={}).status_code == 200
    assert get(api, f"workers/{session}")["worker"]["state"] == "DRAINING"
    assert api.client.post(f"/v1/workers/{session}/stop", headers=owner, json={}).status_code == 200
    stopped = get(api, f"workers/{session}")["worker"]
    assert stopped["state"] == "STOPPED" and stopped["liveness"] == "NOT_APPLICABLE"
    assert stopped["current_attempt"] is None
    history = get(api, f"workers/{session}/attempts")
    assert history["items"][0]["id"] == claimed["attempt_id"]
    lifecycle, cursor = [], "0"
    while True:
        page = get(api, f"workers/{session}/events", after_seq=cursor, limit=1)
        lifecycle.extend(page["items"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert [e["type"] for e in lifecycle] == ["WORKER_REGISTERED", "WORKER_DRAINING", "WORKER_STOPPED"]
    assert [e["seq"] for e in lifecycle] == ["1", "2", "3"]
    assert all("actor_id" not in event for event in lifecycle)


def test_catalogue_and_worker_cursors_and_filters(api):
    jobs = [new_job(api)[0] for _ in range(3)]
    sessions = [register(api)[1]["session_id"] for _ in range(3)]
    first = get(api, "jobs", limit=1, status="QUEUED")
    assert first["items"][0]["id"] == jobs[-1]
    assert first["items"][0]["workload_name"] == "normalize_aggregate"
    collected, cursor = first["items"], first["next_cursor"]
    while cursor:
        page = get(api, "jobs", cursor=cursor, limit=1, status="QUEUED")
        collected.extend(page["items"])
        cursor = page["next_cursor"]
    assert [job["id"] for job in collected] == list(reversed(jobs))
    assert get(api, "jobs", status="FAILED")["items"] == []
    assert api.client.get("/v1/operator/jobs", params={"cursor": first["next_cursor"], "status": "FAILED"},
        headers=api.operator).status_code == 422
    collected, cursor = [], None
    while True:
        page = get(api, "workers", limit=1, **({"after_session": cursor} if cursor else {}))
        collected.extend(page["items"])
        if page["next_cursor"] is None:
            break
        cursor = page["next_cursor"]
    assert [w["session_id"] for w in collected] == sorted(sessions)
    assert get(api, "workers", state="STOPPED")["items"] == []


def test_partition_and_manifest_pages_and_participation_bounds(api):
    job, rows = new_job(api, partitions=3)
    owner = new_owner(api)
    for ordinal in range(3):
        claimed = fresh_claim(api, owner, 1)
        assert claimed["ordinal"] == ordinal
        body, _ = verify_output(api, claimed, owner, rows[ordinal * 12:(ordinal + 1) * 12])
        assert complete(api, claimed, owner, body).status_code == 201
    for suffix in ("partitions", "result-metadata"):
        cursor, ordinals = -1, []
        while True:
            page = get(api, f"jobs/{job}/{suffix}", after_ordinal=cursor, limit=1)
            ordinals.extend(item["ordinal"] for item in page["items"])
            if page["next_cursor"] is None:
                break
            cursor = page["next_cursor"]
        assert ordinals == [0, 1, 2]
    first = get(api, f"workers/{owner['X-Worker-Session']}/attempts", limit=1)
    seen, cursor = first["items"], first["next_cursor"]
    while cursor:
        page = get(api, f"workers/{owner['X-Worker-Session']}/attempts", after_attempt=cursor, limit=1)
        seen.extend(page["items"])
        cursor = page["next_cursor"]
    assert len({a["id"] for a in seen}) == 3
    assert [a["id"] for a in seen] == sorted(a["id"] for a in seen)


def test_invalid_ranges_limits_ids_and_authentication(api):
    job, _ = new_job(api)
    path = f"/v1/operator/jobs/{job}/events"
    for params in ({"after_seq": "9223372036854775808"}, {"after_seq": "-1"}, {"after_seq": "01"},
                   {"after_seq": "١"}, {"after_seq": "1e2"}, {"direction": "backward", "after_seq": "1"},
                   {"before_seq": "4"}, {"after_seq": "2", "before_seq": "3"}, {"limit": 0}, {"limit": 501}):
        response = api.client.get(path, headers=api.operator, params=params)
        assert response.status_code == 422
        assert set(response.json()["error"]) == {"code", "message", "retryable", "outcome", "request_id", "details"}
    for path in ("jobs?cursor=%%", "jobs?limit=501", "jobs?status=INVALID", "workers?after_session=invalid",
                 f"jobs/{job}/partitions?after_ordinal=-2", "workers?state=ONLINE", "jobs?cursor=W10="):
        assert api.client.get("/v1/operator/" + path, headers=api.operator).status_code == 422
    for path in (f"jobs/{uuid4()}", f"partitions/{uuid4()}", f"attempts/{uuid4()}",
                 f"artifacts/{uuid4()}", f"workers/{uuid4()}"):
        assert api.client.get("/v1/operator/" + path, headers=api.operator).status_code == 404
    assert api.client.get(f"/v1/operator/jobs/{job}/events?partition_id={uuid4()}", headers=api.operator).status_code == 404
    for path in ("capabilities", "jobs", "workers", f"jobs/{job}"):
        assert api.client.get("/v1/operator/" + path).status_code == 401
        assert api.client.post("/v1/operator/" + path, headers=api.operator, json={}).status_code == 405
    owner = new_owner(api)
    assert api.client.get("/v1/operator/jobs", headers=owner).status_code == 401


def test_capabilities_revision_and_security_no_raw_failure_detail(api):
    capabilities = get(api, "capabilities")
    assert capabilities["database_revision"] == SCHEMA_REVISION
    assert capabilities["authentication"] == "existing_local_operator_bearer"
    indexed = {capability["id"][:4]: capability for capability in capabilities["capabilities"]}
    assert len(indexed) == 12
    assert {key for key, value in indexed.items() if value["state"] == "DEFERRED"} == {"BV02", "BV10", "BV11"}
    claimed, owner, _ = prepared(api)
    sentinel = "private_failure_detail_" + uuid4().hex
    failure = {key: claimed[key] for key in ("job_id", "partition_id", "generation")} | {
        "code": "worker_crash", "detail": {"secret": sentinel, "nested": [1, {"token": sentinel}]}}
    assert fail_http(api, claimed, owner, failure).status_code == 200
    for path in (f"attempts/{claimed['attempt_id']}", f"partitions/{claimed['partition_id']}",
                 f"jobs/{claimed['job_id']}/events", "workers"):
        response = get(api, path)
        serialized = json.dumps(response)
        assert sentinel not in serialized
        assert "session_secret_hash" not in serialized and "registration_hash" not in serialized
        assert "failure_detail" not in serialized and "last_renew_response" not in serialized
    # SQL projection suppresses large diagnostic objects before Python decodes them.
    with api.admin_engine.begin() as c:
        job = c.execute(sa.select(db.jobs).where(db.jobs.c.id == UUID(claimed["job_id"])).with_for_update()).mappings().one()
        for payload in ({"code": {"nested": sentinel}, "secret": sentinel}, {"secret": sentinel * 1000}, [sentinel]):
            seq = job["next_event_seq"]
            c.execute(db.events.insert().values(job_id=job["id"], seq=seq, type="PUBLICATION_REJECTED",
                actor_type="operator", actor_id="test_fixture", details=payload))
            c.execute(db.jobs.update().where(db.jobs.c.id == job["id"]).values(next_event_seq=seq + 1))
            job = dict(job) | {"next_event_seq": seq + 1}
    events = get(api, f"jobs/{claimed['job_id']}/events")["items"][-3:]
    assert all(event["details"]["state"] == "MALFORMED" for event in events)
    assert all(event["details"]["omitted"] for event in events)
    assert sentinel not in json.dumps(events)
    assert api.client.get(f"/v1/operator/artifacts/{uuid4()}/verification?object_key=../../.env",
        headers=api.operator).status_code == 422


def test_repeatable_read_boundary_and_database_enforced_read_only(api):
    claimed, owner, _ = prepared(api)
    reads = OperatorReads(api.engine, None)
    with reads.snapshot() as (c, t):
        assert c.scalar(sa.text("SHOW transaction_read_only")) == "on"
        assert c.scalar(sa.text("SHOW transaction_isolation")) == "repeatable read"
        before = c.execute(sa.select(db.attempts).where(db.attempts.c.id == UUID(claimed["attempt_id"]))).mappings().one()
        assert before["status"] == "ACTIVE"
        assert fail_http(api, claimed, owner).status_code == 200
        after = c.execute(sa.select(db.attempts).where(db.attempts.c.id == before["id"])).mappings().one()
        assert dict(after) == dict(before)
    assert get(api, f"attempts/{claimed['attempt_id']}")["attempt"]["status"] == "FAILED"
    with pytest.raises(DBAPIError) as error:
        with reads.snapshot() as (c, t):
            c.execute(db.scheduler_state.update().values(next_ticket=db.scheduler_state.c.next_ticket + 1))
    assert error.value.orig.sqlstate == "25006"


def test_metadata_reads_never_touch_store_and_query_count_is_constant(api):
    job, _ = new_job(api, partitions=3)
    app = create_app(api.settings)
    calls = []
    def record(connection, cursor, statement, parameters, context, executemany):
        calls.append(statement)
    with LocalClient(app) as client:
        def forbidden(*args, **kwargs):
            pytest.fail("Passive operator read attempted object storage I/O")
        app.state.gateway.read_exact = forbidden
        app.state.gateway.store.get_object = forbidden
        sa.event.listen(app.state.engine, "before_cursor_execute", record)
        for limit in (1, 3):
            calls.clear()
            response = client.get(f"/v1/operator/jobs/{job}/partitions?limit={limit}", headers=api.operator)
            assert response.status_code == 200
            assert len(response.json()["items"]) == limit
            assert len(calls) == 6  # READ ONLY + clock + existence + page + latest batch + authority batch.
            assert not any("FOR UPDATE" in sql for sql in calls)
        for path in (f"jobs/{job}/definition", f"jobs/{job}/result-metadata", "capabilities", "workers", "jobs"):
            assert client.get("/v1/operator/" + path, headers=api.operator).status_code == 200


def test_actual_pinned_verification_and_missing_version_keeps_authority(api):
    claimed, owner, body = prepared(api)
    assert complete(api, claimed, owner, body).status_code == 201
    row = row_for(api, db.artifacts, body["artifact_id"])
    admin = api.storage[0]
    newer = admin.put_object(Bucket=row["bucket"], Key=row["object_key"], Body=b"different later bytes")
    assert newer["VersionId"] != row["object_version"]
    checked = get(api, f"artifacts/{row['id']}/verification")
    assert checked["verification"]["state"] == "VERIFIED"
    assert checked["verification"]["object_version"] == row["object_version"]
    before = durable_state(api)
    # Same narrowly scoped trusted-admin corruption fixture as the existing M1C test.
    admin.delete_object(Bucket=row["bucket"], Key=row["object_key"], VersionId=row["object_version"])
    failed = get(api, f"artifacts/{row['id']}/verification")
    assert failed["verification"]["state"] == "FAILED"
    assert failed["verification"]["code"] in ("version_unavailable", "storage_missing")
    assert failed["accepted_authority"] == checked["accepted_authority"]
    assert durable_state(api) == before
    assert get(api, f"jobs/{claimed['job_id']}/result-metadata")["items"][0]["authority"] == checked["accepted_authority"]


@pytest.mark.parametrize("kind,code", [("checksum", "checksum_mismatch"), ("size", "size_mismatch"),
    ("version", "version_unavailable"), ("missing", "storage_missing"), ("unreachable", "storage_unavailable"),
    ("transport", "transport_read_failure"), ("content", "content_invalid")])
def test_verification_failure_classification_is_separate_and_observational(api, kind, code):
    claimed, owner, body = prepared(api)
    assert complete(api, claimed, owner, body).status_code == 201
    before = durable_state(api)
    app = create_app(api.settings)
    with LocalClient(app) as client:
        row = row_for(api, db.artifacts, body["artifact_id"])
        def read(**kwargs):
            assert kwargs == dict(Bucket=row["bucket"], Key=row["object_key"], VersionId=row["object_version"])
            if kind in ("version", "missing"):
                raise ClientError({"Error": {"Code": "NoSuchVersion" if kind == "version" else "NoSuchKey"},
                                   "ResponseMetadata": {"HTTPStatusCode": 404}}, "GetObject")
            if kind == "unreachable":
                raise EndpointConnectionError(endpoint_url="http://127.0.0.1:1")
            class Body(io.BytesIO):
                def iter_chunks(self, chunk_size):
                    if kind == "transport":
                        raise OSError("diagnostic transport fixture")
                    if kind == "size":
                        yield b"x" * (row["verified_size_bytes"] + 1)
                    else:
                        yield b"x" * row["verified_size_bytes"]
            return {"Body": Body(), "VersionId": row["object_version"]}
        if kind == "content":
            # Hash/size checks are covered by the checksum and real-store tests;
            # this isolated fixture reaches the Parquet schema/parser failure.
            app.state.gateway.read_exact = lambda *args: io.BytesIO(b"invalid parquet")
        else:
            app.state.gateway.store.get_object = read
        response = client.get(f"/v1/operator/artifacts/{body['artifact_id']}/verification", headers=api.operator)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["verification"]["state"] == "FAILED" and result["verification"]["code"] == code
        assert result["accepted_authority"]["status"] == "ACCEPTED"
        assert result["artifact"]["status"] == "VERIFIED"
        assert result["artifact"]["content_verification"] == "NOT_REQUESTED"
    assert durable_state(api) == before


def test_authority_projection_does_not_infer_from_latest_or_succeeded(api):
    claimed, owner, body = prepared(api)
    assert complete(api, claimed, owner, body).status_code == 201
    with api.engine.connect() as c:
        row = dict(c.execute(attempt_query().where(db.attempts.c.id == UUID(claimed["attempt_id"]))).mappings().one())
    t = datetime.now(timezone.utc)
    # Projection regression only: the current guarded DB cannot normally advance
    # a terminal accepted partition. Never disable guards to manufacture this state.
    different = row | {"current_generation": 2}
    observation = attempt_model(different, t)
    assert observation.current_generation == "2" and observation.accepted_authority.result.generation == "1"
    assert observation.accepted_authority.result.attempt_id == UUID(claimed["attempt_id"])
    absent = row | {key: None for key in row if key.startswith("r_")}
    observed = attempt_model(absent, t)
    assert observed.status == "SUCCEEDED" and observed.accepted_authority.status == "NONE"
    assert not observed.is_accepted_attempt
    assert authority(None).status == "NONE"


def test_new_indexes_exist_and_support_operator_access_paths(api):
    job, _ = new_job(api)
    owner = new_owner(api)
    claimed = fresh_claim(api, owner, 1)
    shapes = [
        (job_query().order_by(db.jobs.c.created_at.desc(), db.jobs.c.id.desc()).limit(101), "ix_jobs_operator_created"),
        (job_query().where(db.jobs.c.status == "RUNNING").order_by(db.jobs.c.created_at.desc(), db.jobs.c.id.desc())
            .limit(101), "ix_jobs_operator_status_created"),
        (attempt_query().where(db.attempts.c.worker_session_id == UUID(owner["X-Worker-Session"]))
            .order_by(db.attempts.c.id).limit(101), "ix_attempts_operator_worker"),
        (sa.select(db.events).where(db.events.c.job_id == UUID(job), db.events.c.attempt_id == UUID(claimed["attempt_id"]))
            .order_by(db.events.c.seq).limit(101), "ix_events_operator_attempt"),
    ]
    with api.engine.connect() as c:
        c.execute(sa.text("SET LOCAL enable_seqscan = off"))
        for statement, name in shapes:
            sql = str(statement.compile(dialect=c.dialect, compile_kwargs={"literal_binds": True}))
            plan = c.exec_driver_sql("EXPLAIN (FORMAT JSON) " + sql).scalar_one()
            assert name in json.dumps(plan), json.dumps(plan)
    print("R1 index access paths", [name for _, name in shapes])
