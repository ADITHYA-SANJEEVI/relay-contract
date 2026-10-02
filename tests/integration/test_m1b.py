import hashlib
import asyncio
import io
import json
import os
import secrets
import subprocess
import sys
from datetime import datetime
from uuid import UUID, uuid4

import pyarrow as pa
import pytest
import sqlalchemy as sa
import httpx

from relay.api.app import create_app
from relay.db import schema as db
from relay.workloads.reference import (INPUT_SCHEMA, INPUT_SCHEMA_HASH, OUTPUT_SCHEMA, OUTPUT_SCHEMA_HASH,
                                       execute, read_parquet, write_parquet)
from tests.unit.oracle import serial_oracle

from .conftest import (ROOT, claim, parquet_bytes, register, reserve_input, submission,
                       submit_job, verified_input)


def row_for(api, table, identity):
    with api.engine.connect() as c:
        return dict(c.execute(sa.select(table).where(table.c.id == UUID(identity))).mappings().one())


def active_claim(api):
    identity, data, rows = verified_input(api)
    response = submit_job(api, submission(identity, len(rows)))
    assert response.status_code == 201, response.text
    registered, body, headers = register(api)
    assert registered.status_code == 201, registered.text
    claimed = claim(api, headers)
    assert claimed.status_code == 201, claimed.text
    return claimed.json(), headers, rows


def output_bytes(rows):
    table, _ = execute([pa.Table.from_pylist(rows, schema=INPUT_SCHEMA)])
    output = io.BytesIO(); write_parquet(table, output)
    return output.getvalue()


def reserve_output(api, claimed, headers, data, **changes):
    body = {k: claimed[k] for k in ("job_id", "partition_id", "generation")} | dict(
        sha256=hashlib.sha256(data).hexdigest(), size_bytes=str(len(data)), schema_hash=OUTPUT_SCHEMA_HASH) | changes
    response = api.client.post(f"/v1/attempts/{claimed['attempt_id']}/artifact", headers=headers, json=body)
    return response, body


def test_input_idempotency_pin_and_real_bytes(api):
    data = parquet_bytes([]); key = str(uuid4())
    first, body = reserve_input(api, data, key=key)
    repeat, _ = reserve_input(api, data, key=key)
    conflict, _ = reserve_input(api, data, key=key, sha256="a" * 64)
    assert (first.status_code, repeat.status_code, conflict.status_code) == (201, 200, 409)
    assert first.json()["id"] == repeat.json()["id"]
    identity = first.json()["id"]
    response = api.client.put(f"/v1/inputs/{identity}/content", headers=api.operator, content=data)
    assert response.status_code == 200, response.text
    verified = response.json()
    repeated = api.client.put(f"/v1/inputs/{identity}/content", headers=api.operator, content=data)
    assert repeated.json() == verified
    persisted = row_for(api, db.input_artifacts, identity)
    assert persisted["status"] == "VERIFIED" and persisted["row_count"] == 0
    assert verified["object_version"] == persisted["object_version"]
    runtime = api.storage[1]
    stored = runtime.get_object(Bucket=persisted["bucket"], Key=persisted["object_key"], VersionId=persisted["object_version"])
    with stored["Body"] as stream: actual = stream.read()
    assert actual == data and hashlib.sha256(actual).hexdigest() == persisted["sha256"]
    versions = api.storage[0].list_object_versions(Bucket=persisted["bucket"], Prefix=persisted["object_key"])["Versions"]
    assert len(versions) == 1
    assert api.client.get(f"/v1/inputs/{identity}", headers=api.operator).json()["status"] == "VERIFIED"


def test_input_incorrect_hash_rejected(api):
    data = parquet_bytes([])
    response, _ = reserve_input(api, data, sha256="b" * 64)
    assert response.status_code == 201
    identity = response.json()["id"]
    bad = api.client.put(f"/v1/inputs/{identity}/content", headers=api.operator, content=data)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "content_identity_mismatch"
    assert row_for(api, db.input_artifacts, identity)["status"] == "RESERVED"


def test_noncanonical_parquet_rejected(api):
    output = io.BytesIO()
    import pyarrow.parquet as pq
    pq.write_table(pa.table({"arbitrary": [1]}), output)
    data = output.getvalue()
    first, _ = reserve_input(api, data)
    assert first.status_code == 201
    identity = first.json()["id"]
    response = api.client.put(f"/v1/inputs/{identity}/content", headers=api.operator, content=data)
    assert response.status_code == 422
    assert row_for(api, db.input_artifacts, identity)["status"] == "REJECTED"


def test_storage_io_without_open_transaction_and_conditional_protocol(api):
    app = create_app(api.settings)
    observed = []
    versions_read = []
    def observe(model, params, **kwargs):
        assert app.state.engine.pool.checkedout() == 0
        with api.admin_engine.connect() as c:
            assert c.scalar(sa.text("SELECT count(*) FROM pg_stat_activity WHERE datname=:name "
                "AND usename='relay_runtime' AND xact_start IS NOT NULL"), {"name": api.database}) == 0
        if model.name == "PutObject":
            assert params["headers"]["If-None-Match"] == "*"
        observed.append(model.name)
    def observe_version(params, **kwargs): versions_read.append(params["VersionId"])
    app.state.gateway.store.meta.events.register("before-call.s3.PutObject", observe)
    app.state.gateway.store.meta.events.register("before-call.s3.GetObject", observe)
    app.state.gateway.store.meta.events.register("before-parameter-build.s3.GetObject", observe_version)
    data = parquet_bytes([])
    async def request_path():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                first = await client.post("/v1/inputs", headers=api.operator | {"Idempotency-Key": str(uuid4())}, json=dict(
                    sha256=hashlib.sha256(data).hexdigest(), size_bytes=str(len(data)), media_type="application/vnd.apache.parquet", schema_hash=INPUT_SCHEMA_HASH))
                assert first.status_code == 201, first.text
                response = await client.put(first.json()["upload_url"], headers=api.operator, content=data)
                assert response.status_code == 200, response.text
                return response
    response = asyncio.run(request_path())
    assert observed == ["PutObject", "GetObject"]
    assert versions_read == [response.json()["object_version"]]


def test_valid_manifest_submission_idempotency_and_rerun(api):
    identity, data, rows = verified_input(api)
    body = submission(identity, len(rows), split=[(0, 5), (5, len(rows)-5)])
    key = str(uuid4())
    first, repeated = submit_job(api, body, key), submit_job(api, body, key)
    assert (first.status_code, repeated.status_code) == (201, 200)
    assert first.json() == repeated.json()
    changed = body | {"policy": {"max_attempts": 4}}
    assert submit_job(api, changed, key).status_code == 409
    rerun = submit_job(api, body)
    assert rerun.status_code == 201 and rerun.json()["id"] != first.json()["id"]
    assert rerun.json()["definition_hash"] == first.json()["definition_hash"]
    job = UUID(first.json()["id"])
    with api.engine.connect() as c:
        parts = c.execute(sa.select(db.partitions).where(db.partitions.c.job_id == job).order_by(db.partitions.c.ordinal)).mappings().all()
        assert [p["ordinal"] for p in parts] == [0, 1]
        assert all(p["generation"] == 0 and p["latest_generation_fk"] is None for p in parts)
        assert c.scalar(sa.select(sa.func.count()).select_from(db.partition_inputs).where(db.partition_inputs.c.job_id == job)) == 2
        assert c.scalar(sa.select(sa.func.count()).select_from(db.job_inputs).where(db.job_inputs.c.job_id == job)) == 1
    read = api.client.get(f"/v1/jobs/{job}", headers=api.operator).json()
    assert read["partition_count"] == "2" and read["partial_result_count"] == "0" and not read["complete"]
    page = api.client.get(f"/v1/jobs/{job}/partitions?limit=1", headers=api.operator).json()
    assert page["items"][0]["ordinal"] == 0 and page["next_cursor"] == 0


@pytest.mark.parametrize("kind", ["overlap", "gap", "ordinal", "workload", "unknown_field", "bounds"])
def test_invalid_submission_leaves_no_partial_rows(api, kind):
    identity, data, rows = verified_input(api)
    body = submission(identity, len(rows))
    if kind == "overlap": body = submission(identity, len(rows), split=[(0, 7), (6, len(rows)-6)])
    if kind == "gap": body = submission(identity, len(rows), split=[(0, 5), (6, len(rows)-6)])
    if kind == "ordinal": body["partitions"][0]["ordinal"] = 1
    if kind == "workload": body["workload"] = body["workload"] | {"digest": "sha256:" + "b" * 64}
    if kind == "unknown_field": body["external_url"] = "http://example.invalid/input"
    if kind == "bounds": body["partitions"][0]["slices"][0]["row_count"] = str(len(rows) + 1)
    response = submit_job(api, body)
    assert response.status_code == 422, response.text
    with api.engine.connect() as c:
        for table in (db.jobs, db.partitions, db.partition_inputs, db.job_inputs, db.events, db.request_receipts):
            assert c.scalar(sa.select(sa.func.count()).select_from(table)) == 0
        assert c.scalar(sa.select(db.scheduler_state.c.next_ticket)) == 1


def test_unverified_input_submission_rejected(api):
    response, _ = reserve_input(api, parquet_bytes([]))
    result = submit_job(api, submission(response.json()["id"], 0))
    assert result.status_code == 422 and result.json()["error"]["code"] == "input_not_verified"
    with api.engine.connect() as c: assert c.scalar(sa.select(sa.func.count()).select_from(db.jobs)) == 0


def test_submission_real_database_abort_rolls_back_entire_manifest(api):
    identity, data, rows = verified_input(api)
    body = submission(identity, len(rows), split=[(0, 5), (5, len(rows)-5)])
    # Additional test-only rejecting constraint; original M1A guards remain enabled.
    with api.admin_engine.begin() as c:
        c.exec_driver_sql("CREATE FUNCTION reject_fixture_partition() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            "IF NEW.ordinal=1 THEN RAISE EXCEPTION 'fixture rejection' USING ERRCODE='23514'; END IF; RETURN NEW; END; $$")
        c.exec_driver_sql("CREATE TRIGGER reject_fixture BEFORE INSERT ON partitions FOR EACH ROW EXECUTE FUNCTION reject_fixture_partition()")
    key = str(uuid4())
    try:
        rejected = submit_job(api, body, key)
        assert rejected.status_code == 503
        assert rejected.json()["error"]["outcome"] == "not_committed"
        with api.engine.connect() as c:
            for table in (db.jobs, db.partitions, db.partition_inputs, db.job_inputs, db.events, db.request_receipts):
                assert c.scalar(sa.select(sa.func.count()).select_from(table)) == 0
            assert c.scalar(sa.select(db.scheduler_state.c.next_ticket)) == 1
    finally:
        with api.admin_engine.begin() as c:
            c.exec_driver_sql("DROP TRIGGER reject_fixture ON partitions")
            c.exec_driver_sql("DROP FUNCTION reject_fixture_partition()")
    assert submit_job(api, body, key).status_code == 201


def test_empty_input_has_explicit_empty_partition(api):
    identity, data, rows = verified_input(api, [])
    assert submit_job(api, submission(identity, 0)).status_code == 201


def test_registration_binding_and_secret_hygiene(api):
    response, body, headers = register(api)
    assert response.status_code == 201
    exact = api.client.post("/v1/workers/register", headers=api.bootstrap, json=body)
    changed = api.client.post("/v1/workers/register", headers=api.bootstrap, json=body | {"display_name": "changed"})
    assert exact.status_code == 200 and exact.json() == response.json()
    assert changed.status_code == 409
    with api.admin_engine.connect() as c:
        raw = c.execute(sa.text("SELECT row_to_json(workers)::text FROM workers")).scalar_one()
        secret_absent = body["session_secret"] not in raw
        assert secret_absent, "Session secret unexpectedly present in database (redacted)"
        assert c.scalar(sa.select(db.workers.c.session_secret_hash)) == hashlib.sha256(body["session_secret"].encode()).hexdigest()
        assert c.scalar(sa.select(sa.func.count()).select_from(db.attempts)) == 0
        assert c.execute(sa.select(db.worker_events.c.seq, db.worker_events.c.type)).all() == [(1, "WORKER_REGISTERED")]
    secret_absent = body["session_secret"] not in api.log_path.read_text()
    assert secret_absent, "Session secret unexpectedly present in logs (redacted)"


def test_claim_generation_lease_events_ticket_and_replay(api):
    identity, data, rows = verified_input(api)
    submitted = submit_job(api, submission(identity, len(rows))).json()
    response, body, headers = register(api)
    with api.engine.connect() as c: before = c.scalar(sa.select(db.scheduler_state.c.next_ticket))
    key = str(uuid4())
    claimed = claim(api, headers, key)
    assert claimed.status_code == 201, claimed.text
    first = claimed.json()
    repeat = claim(api, headers, key)
    assert repeat.status_code == 200 and repeat.json() == first | {"replay": True}
    with api.engine.connect() as c:
        attempt = c.execute(sa.select(db.attempts)).mappings().one()
        assert attempt["status"] == "ACTIVE" and attempt["generation"] == 1
        assert str(attempt["worker_session_id"]) == body["session_id"]
        assert (attempt["lease_expires_at"]-attempt["claimed_at"]).total_seconds() == 30
        assert (attempt["hard_deadline_at"]-attempt["claimed_at"]).total_seconds() == 600
        assert str(attempt["id"]) == first["attempt_id"] and attempt["lease_expires_at"].isoformat() == first["lease_expires_at"]
        partition = c.execute(sa.select(db.partitions)).mappings().one()
        assert (partition["status"], partition["generation"], partition["latest_generation_fk"]) == ("RUNNING", 1, 1)
        job = c.execute(sa.select(db.jobs)).mappings().one()
        assert job["status"] == "RUNNING" and job["fair_ticket"] == before and job["next_event_seq"] == 5
        assert c.scalar(sa.select(db.scheduler_state.c.next_ticket)) == before+1
        events = c.execute(sa.select(db.events.c.seq, db.events.c.type).order_by(db.events.c.seq)).all()
        assert events == [(1,"JOB_SUBMITTED"), (2,"ATTEMPT_CLAIMED"), (3,"PARTITION_RUNNING"), (4,"JOB_RUNNING")]
        assert c.scalar(sa.select(sa.func.count()).select_from(db.attempts)) == 1
        assert c.scalar(sa.select(sa.func.count()).select_from(db.request_receipts).where(db.request_receipts.c.operation == "claim")) == 1
    assert claim(api, headers).status_code == 409  # Busy, no second generation.


def test_no_work_204_receipt_is_durable_even_after_submission(api):
    response, body, headers = register(api)
    key = str(uuid4())
    assert claim(api, headers, key).status_code == 204
    identity, data, rows = verified_input(api)
    assert submit_job(api, submission(identity, len(rows))).status_code == 201
    assert claim(api, headers, key).status_code == 204
    assert claim(api, headers).status_code == 201
    with api.engine.connect() as c:
        receipt = c.execute(sa.select(db.request_receipts).where(db.request_receipts.c.key == key)).mappings().one()
        assert receipt["status_code"] == 204 and receipt["response"] == {}


def test_artifact_reservation_upload_and_no_authority(api):
    claimed, headers, rows = active_claim(api)
    data = output_bytes(rows)
    reserved, body = reserve_output(api, claimed, headers, data)
    assert reserved.status_code == 201, reserved.text
    repeat = api.client.post(f"/v1/attempts/{claimed['attempt_id']}/artifact", headers=headers, json=body)
    altered = api.client.post(f"/v1/attempts/{claimed['attempt_id']}/artifact", headers=headers, json=body | {"sha256": "c" * 64})
    assert repeat.status_code == 200 and repeat.json() == reserved.json()
    assert altered.status_code == 409
    identity = reserved.json()["id"]
    response = api.client.put(reserved.json()["upload_url"], headers=headers, content=data)
    assert response.status_code == 200, response.text
    verified = response.json()
    assert verified["status"] == "VERIFIED" and verified["sha256"] == hashlib.sha256(data).hexdigest()
    assert verified["schema_hash"] == OUTPUT_SCHEMA_HASH
    assert api.client.put(reserved.json()["upload_url"], headers=headers, content=data).json() == verified
    assert api.client.put(reserved.json()["upload_url"], headers=headers, content=b"conflicting").status_code == 422
    artifact = row_for(api, db.artifacts, identity)
    stored = api.storage[1].get_object(Bucket=artifact["bucket"], Key=artifact["object_key"], VersionId=artifact["object_version"])
    with stored["Body"] as stream: actual = stream.read()
    assert actual == data and hashlib.sha256(actual).hexdigest() == artifact["verified_sha256"]
    assert read_parquet(pa.BufferReader(actual), OUTPUT_SCHEMA).to_pylist() == serial_oracle(rows)[0]
    assert len(api.storage[0].list_object_versions(Bucket=artifact["bucket"], Prefix=artifact["object_key"])["Versions"]) == 1
    assert artifact["object_key"] == f"jobs/{claimed['job_id']}/partitions/0/attempt-1/{identity}/output.parquet"
    with api.engine.connect() as c:
        assert c.scalar(sa.select(db.attempts.c.status)) == "ACTIVE"
        assert c.scalar(sa.select(db.partitions.c.status)) == "RUNNING"
        assert c.scalar(sa.select(db.jobs.c.status)) == "RUNNING"
        assert c.scalar(sa.select(sa.func.count()).select_from(db.accepted_results)) == 0
    read = api.client.get(f"/v1/attempts/{claimed['attempt_id']}", headers=headers).json()
    assert read["artifact"]["status"] == "VERIFIED" and read["accepted_result"] is None
    job = api.client.get(f"/v1/jobs/{claimed['job_id']}", headers=api.operator).json()
    assert not job["complete"] and job["partial_result_count"] == "0"


@pytest.mark.parametrize("kind", ["owner", "generation", "lease", "job_id", "schema"])
def test_artifact_reservation_requires_live_exact_ownership(api, kind):
    claimed, headers, rows = active_claim(api)
    changes = {}
    if kind == "owner":
        response, body, headers = register(api)
    if kind == "generation": changes["generation"] = "2"
    if kind == "job_id": changes["job_id"] = str(uuid4())
    if kind == "schema": changes["schema_hash"] = "b" * 64
    if kind == "lease":
        # Test-only deadline movement under the normal lock order. No settlement.
        with api.engine.begin() as c:
            c.execute(sa.select(db.jobs).with_for_update())
            c.execute(sa.select(db.partitions).with_for_update())
            c.execute(sa.select(db.attempts).with_for_update())
            c.execute(db.attempts.update().values(lease_expires_at=db.attempts.c.claimed_at + sa.text("interval '1 microsecond'")))
    response, body = reserve_output(api, claimed, headers, output_bytes(rows), **changes)
    assert response.status_code in (403, 404, 409, 422)
    if kind == "lease": assert response.json()["error"]["code"] == "lease_expired"
    with api.engine.connect() as c: assert c.scalar(sa.select(sa.func.count()).select_from(db.artifacts)) == 0


def test_reserved_key_reconciliation_after_real_store_write(api):
    claimed, headers, rows = active_claim(api)
    data = output_bytes(rows)
    reservation, body = reserve_output(api, claimed, headers, data)
    artifact = row_for(api, db.artifacts, reservation.json()["id"])
    written = api.storage[1].put_object(Bucket=artifact["bucket"], Key=artifact["object_key"],
                                      Body=data, IfNoneMatch="*")
    assert artifact["object_version"] is None and artifact["status"] == "RESERVED"
    result = api.client.put(reservation.json()["upload_url"], headers=headers, content=data)
    assert result.status_code == 200 and result.json()["object_version"] == written["VersionId"]
    assert len(api.storage[0].list_object_versions(Bucket=artifact["bucket"], Prefix=artifact["object_key"])["Versions"]) == 1


def test_artifact_wrong_actual_output_schema_rejected(api):
    claimed, headers, rows = active_claim(api)
    data = parquet_bytes(rows)  # Input schema cannot masquerade as output.
    reserved, _ = reserve_output(api, claimed, headers, data)
    assert reserved.status_code == 201
    response = api.client.put(reserved.json()["upload_url"], headers=headers, content=data)
    assert response.status_code == 422
    assert row_for(api, db.artifacts, reserved.json()["id"])["status"] == "REJECTED"


def test_claim_replay_after_unsettled_expiry_never_extends_lease(api):
    identity, data, rows = verified_input(api)
    assert submit_job(api, submission(identity, len(rows))).status_code == 201
    response, body, headers = register(api)
    key = str(uuid4())
    first = claim(api, headers, key).json()
    with api.engine.begin() as c:
        c.execute(sa.select(db.jobs).with_for_update())
        c.execute(sa.select(db.partitions).with_for_update())
        c.execute(sa.select(db.attempts).with_for_update())
        c.execute(db.attempts.update().values(lease_expires_at=db.attempts.c.claimed_at + sa.text("interval '1 microsecond'")))
    repeated = claim(api, headers, key)
    assert repeated.status_code == 200 and repeated.json() == first | {"replay": True}
    current = api.client.get(f"/v1/attempts/{first['attempt_id']}", headers=headers).json()
    assert datetime.fromisoformat(current["db_time"]) >= datetime.fromisoformat(current["lease_expires_at"])
    with api.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.attempts)) == 1
        assert c.scalar(sa.select(db.partitions.c.generation)) == 1


def test_m1b_precursor_independent_worker_process(api):
    identity, data, rows = verified_input(api)
    first_count = 5
    job = submit_job(api, submission(identity, len(rows), split=[(0, first_count), (first_count, len(rows)-first_count)]))
    assert job.status_code == 201
    # Deliberately restricted environment: no DB/store/operator credentials.
    env = {k: v for k,v in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC", "PATHEXT", "USERPROFILE")}
    env["RELAY_WORKER_BOOTSTRAP_TOKEN"] = api.settings["RELAY_WORKER_BOOTSTRAP_TOKEN"]
    assert not any(k.startswith(("POSTGRES_", "S3_", "AWS_")) for k in env)
    completed = subprocess.run([sys.executable, str(ROOT / "scripts/run_worker.py"), "--base-url", api.url],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert completed.returncode == 0, completed.stderr + completed.stdout
    trace = json.loads(completed.stdout)
    assert trace["phase"] == "VERIFIED_UNACCEPTED" and trace["generation"] == "1"
    assert trace["worker_pid"] not in (os.getpid(), api.pid)
    artifact = row_for(api, db.artifacts, trace["artifact_id"])
    stored = api.storage[1].get_object(Bucket=artifact["bucket"], Key=artifact["object_key"], VersionId=trace["object_version"])
    with stored["Body"] as body: output = body.read()
    expected, counters = serial_oracle(rows[:first_count])
    assert read_parquet(pa.BufferReader(output), OUTPUT_SCHEMA).to_pylist() == expected
    assert trace["counters"] == counters and hashlib.sha256(output).hexdigest() == trace["sha256"]
    with api.engine.connect() as c:
        assert artifact["status"] == "VERIFIED"
        assert c.scalar(sa.select(db.attempts.c.status)) == "ACTIVE"
        assert c.execute(sa.select(db.partitions.c.status).order_by(db.partitions.c.ordinal)).scalars().all() == ["RUNNING", "READY"]
        assert c.scalar(sa.select(db.jobs.c.status)) == "RUNNING"
        assert c.scalar(sa.select(sa.func.count()).select_from(db.accepted_results)) == 0
    for value in (api.settings["POSTGRES_RUNTIME_PASSWORD"], api.settings["S3_RUNTIME_SECRET_KEY"], api.settings["RELAY_WORKER_BOOTSTRAP_TOKEN"]):
        credential_absent = value not in completed.stdout + completed.stderr + api.log_path.read_text()
        assert credential_absent, "Credential unexpectedly present in process output (redacted)"
    print("M1B PRECURSOR", json.dumps(trace, sort_keys=True))


def test_auth_unknown_fields_and_unimplemented_endpoints(api):
    assert api.client.get("/health/live").json() == {"live": True}
    assert api.client.post("/v1/inputs", json={}).status_code == 401
    unknown = api.client.post("/v1/workers/register", headers=api.bootstrap, json={"session_secret": "secret", "unknown": True})
    assert unknown.status_code == 422 and "secret" not in unknown.text and "traceback" not in unknown.text.lower()
    # M1C adds complete; its unauthenticated path must still reject access.
    assert api.client.post(f"/v1/attempts/{uuid4()}/complete").status_code == 401
    # M2 adds renewal; retain auth denial and the remaining forbidden endpoints.
    assert api.client.post(f"/v1/attempts/{uuid4()}/renew").status_code == 401
    # M3 adds server-classified failure; unauthenticated calls remain denied.
    assert api.client.post(f"/v1/attempts/{uuid4()}/fail").status_code == 401
    assert api.client.post(f"/v1/jobs/{uuid4()}/cancel").status_code == 404
