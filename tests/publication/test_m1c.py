import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID, uuid4

import httpx
import pyarrow as pa
import pytest
import sqlalchemy as sa

from relay.control.publication import FENCED_UPDATE
from relay.db import schema as db
from relay.workloads.reference import OUTPUT_SCHEMA, read_parquet
from tests.integration.conftest import ROOT, claim, register, submission, submit_job, verified_input
from tests.integration.test_m1b import active_claim, output_bytes, reserve_output, row_for
from tests.unit.oracle import serial_oracle
from tests.unit.test_reference import fixture_rows


def prepared(api):
    claimed, headers, rows = active_claim(api)
    data = output_bytes(rows)
    reserved, _ = reserve_output(api, claimed, headers, data)
    assert reserved.status_code == 201
    verified = api.client.put(reserved.json()["upload_url"], headers=headers, content=data)
    assert verified.status_code == 200, verified.text
    body = {k: claimed[k] for k in ("job_id", "partition_id", "generation")} | {
        "request_id": str(uuid4()), "artifact_id": verified.json()["id"],
        "artifact_uri": verified.json()["artifact_uri"], "sha256": verified.json()["sha256"]}
    return claimed, headers, body


def complete(api, claimed, headers, body):
    return api.client.post(f"/v1/attempts/{claimed['attempt_id']}/complete", headers=headers, json=body)


def accepted_rows(api):
    with api.engine.connect() as c:
        return [dict(row) for row in c.execute(sa.select(db.accepted_results)).mappings()]


def events(api):
    with api.engine.connect() as c:
        return [dict(row) for row in c.execute(sa.select(db.events).order_by(db.events.c.seq)).mappings()]


SUCCESS = ["ATTEMPT_SUCCEEDED", "PARTITION_SUCCEEDED", "RESULT_ACCEPTED", "JOB_SUCCEEDED"]


def assert_unaccepted(api, claimed):
    assert accepted_rows(api) == []
    assert row_for(api, db.partitions, claimed["partition_id"])["status"] == "RUNNING"
    assert row_for(api, db.attempts, claimed["attempt_id"])["status"] == "ACTIVE"
    assert row_for(api, db.jobs, claimed["job_id"])["status"] == "RUNNING"
    assert not any(e["type"] in SUCCESS for e in events(api))


def shorten_lease(api, claimed, *, expired=False, seconds=1.25):
    with api.engine.begin() as c:
        c.execute(sa.select(db.jobs).where(db.jobs.c.id == UUID(claimed["job_id"])).with_for_update())
        c.execute(sa.select(db.partitions).where(db.partitions.c.id == UUID(claimed["partition_id"])).with_for_update())
        c.execute(sa.select(db.attempts).where(db.attempts.c.id == UUID(claimed["attempt_id"])).with_for_update())
        value = db.attempts.c.claimed_at + sa.text("interval '1 microsecond'") if expired else (
            sa.func.clock_timestamp() + sa.text(f"interval '{seconds} seconds'"))
        return c.execute(db.attempts.update().where(db.attempts.c.id == UUID(claimed["attempt_id"]))
                         .values(lease_expires_at=value).returning(db.attempts.c.lease_expires_at)).scalar_one()


def test_fresh_acceptance_atomic_state_events_and_reads(api):
    claimed, headers, body = prepared(api)
    artifact_before = row_for(api, db.artifacts, body["artifact_id"])
    assert complete(api, claimed, headers, body | {"unknown": True}).status_code == 422
    assert complete(api, claimed, headers, body | {"request_id": "x"*129}).status_code == 422
    assert api.client.get(f"/v1/jobs/{claimed['job_id']}/results", headers=api.operator).json()["items"] == []
    assert api.client.get(f"/v1/artifacts/{body['artifact_id']}/content", headers=api.operator).status_code == 404
    own_content = api.client.get(f"/v1/artifacts/{body['artifact_id']}/content", headers=headers)
    assert own_content.status_code == 200 and hashlib.sha256(own_content.content).hexdigest() == body["sha256"]
    response = complete(api, claimed, headers, body)
    assert response.status_code == 201, response.text
    result = response.json()
    assert not result["replay"] and result["job_status"] == "SUCCEEDED"
    assert len(accepted_rows(api)) == 1
    t = datetime.fromisoformat(result["accepted_result"]["accepted_at"])
    assert t < datetime.fromisoformat(claimed["lease_expires_at"])
    for table, identity in ((db.jobs, claimed["job_id"]), (db.partitions, claimed["partition_id"]), (db.attempts, claimed["attempt_id"])):
        row = row_for(api, table, identity)
        assert row["status"] == "SUCCEEDED" and row["finished_at"] == t
    assert row_for(api, db.artifacts, body["artifact_id"]) == artifact_before
    history = events(api)
    assert [e["type"] for e in history[-4:]] == SUCCESS
    assert [e["seq"] for e in history] == list(range(1, len(history)+1))
    assert all(e["occurred_at"] == t and e["request_id"] == body["request_id"] for e in history[-4:])
    job = api.client.get(f"/v1/jobs/{claimed['job_id']}", headers=api.operator).json()
    assert job["complete"] and job["partial_result_count"] == "1"
    part = api.client.get(f"/v1/jobs/{claimed['job_id']}/partitions", headers=api.operator).json()["items"][0]
    assert part["accepted_artifact_id"] == body["artifact_id"] and part["status"] == "SUCCEEDED"
    attempt = api.client.get(f"/v1/attempts/{claimed['attempt_id']}", headers=headers).json()
    assert attempt["accepted_result"]["artifact_id"] == body["artifact_id"]
    print("M1C ACCEPTANCE", json.dumps(claimed | result, sort_keys=True))


def test_exact_accepted_replay_after_deadline_preserves_identity(api):
    claimed, headers, body = prepared(api)
    deadline = shorten_lease(api, claimed, seconds=1.25)
    first = complete(api, claimed, headers, body)
    assert first.status_code == 201
    before = accepted_rows(api)
    # Real DB-clock deadline crossing, without modifying terminal attempt metadata.
    with api.admin_engine.connect() as c:
        while c.scalar(sa.select(sa.func.clock_timestamp())) <= deadline:
            time.sleep(0.02)
    for request_id in (body["request_id"], str(uuid4())):
        repeated = complete(api, claimed, headers, body | {"request_id": request_id})
        assert repeated.status_code == 200 and repeated.json()["replay"]
        assert repeated.json()["accepted_result"] == first.json()["accepted_result"]
    assert accepted_rows(api) == before
    assert [e["type"] for e in events(api)].count("RESULT_ACCEPTED") == 1
    print("M1C REPLAY", json.dumps(first.json(), sort_keys=True))


@pytest.mark.parametrize("kind", ["artifact", "sha", "older_generation", "newer_generation", "uri"])
def test_conflict_cannot_replace_accepted_result(api, kind):
    claimed, headers, body = prepared(api)
    assert complete(api, claimed, headers, body).status_code == 201
    before = accepted_rows(api)
    changed = body | {"request_id": str(uuid4())}
    if kind == "artifact": changed["artifact_id"] = str(uuid4())
    if kind == "sha": changed["sha256"] = "a"*64
    if kind == "older_generation": changed["generation"] = "0"
    if kind == "newer_generation": changed["generation"] = "2"
    if kind == "uri": changed["artifact_uri"] += "-other"
    response = complete(api, claimed, headers, changed)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == ("stale_generation" if kind == "older_generation" else "result_conflict")
    assert accepted_rows(api) == before
    assert [e["type"] for e in events(api)].count("RESULT_ACCEPTED") == 1
    assert complete(api, claimed, headers, changed).json() == response.json()
    assert [e["type"] for e in events(api)].count("PUBLICATION_REJECTED") == 1


@pytest.mark.parametrize("kind", ["owner", "generation", "artifact", "sha", "external_uri", "wrong_job", "unknown_attempt"])
def test_wrong_publication_identity_has_no_authority(api, kind):
    claimed, headers, body = prepared(api)
    changed = dict(body)
    supplied = dict(claimed)
    if kind == "owner":
        _, _, headers = register(api)
    if kind == "generation": changed["generation"] = "0"
    if kind == "artifact": changed["artifact_id"] = str(uuid4())
    if kind == "sha": changed["sha256"] = "b"*64
    if kind == "external_uri": changed["artifact_uri"] = "https://example.invalid/output.parquet"
    if kind == "wrong_job": changed["job_id"] = str(uuid4())
    if kind == "unknown_attempt": supplied["attempt_id"] = str(uuid4())
    response = complete(api, supplied, headers, changed)
    assert response.status_code == (403 if kind == "owner" else 404 if kind in ("wrong_job", "unknown_attempt") else 409)
    assert_unaccepted(api, claimed)
    assert complete(api, supplied, headers, changed).json() == response.json()
    with api.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.request_receipts).where(db.request_receipts.c.operation == "complete")) == 1


def test_expired_fresh_publication_rejected_and_audit_deduplicated(api):
    claimed, headers, body = prepared(api)
    shorten_lease(api, claimed, expired=True)
    response = complete(api, claimed, headers, body)
    assert response.status_code == 409 and response.json()["error"]["code"] == "lease_expired"
    assert complete(api, claimed, headers, body).json() == response.json()
    assert_unaccepted(api, claimed)
    assert [e["type"] for e in events(api)].count("PUBLICATION_REJECTED") == 1
    changed = complete(api, claimed, headers, body | {"sha256": "c"*64})
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "idempotency_conflict"
    assert [e["type"] for e in events(api)].count("PUBLICATION_REJECTED") == 1
    print("M1C EXPIRED", json.dumps(response.json(), sort_keys=True))


def test_unverified_rejection_requires_new_request_id_after_correction(api):
    claimed, headers, rows = active_claim(api)
    data = output_bytes(rows)
    reserved, metadata = reserve_output(api, claimed, headers, data)
    artifact = row_for(api, db.artifacts, reserved.json()["id"])
    body = {k: claimed[k] for k in ("job_id", "partition_id", "generation")} | {
        "request_id": str(uuid4()), "artifact_id": reserved.json()["id"], "sha256": metadata["sha256"],
        "artifact_uri": f"s3://{artifact['bucket']}/{artifact['object_key']}?versionId=not-verified"}
    first = complete(api, claimed, headers, body)
    assert first.status_code == 409 and first.json()["error"]["code"] == "artifact_not_verified"
    verified = api.client.put(reserved.json()["upload_url"], headers=headers, content=data)
    assert verified.status_code == 200
    assert complete(api, claimed, headers, body).json() == first.json()
    corrected = body | {"artifact_uri": verified.json()["artifact_uri"]}
    assert complete(api, claimed, headers, corrected).json()["error"]["code"] == "idempotency_conflict"
    assert complete(api, claimed, headers, corrected | {"request_id": str(uuid4())}).status_code == 201


def test_abort_after_fenced_mutation_rolls_back_all_success(api):
    claimed, headers, body = prepared(api)
    before_events = events(api)
    with api.admin_engine.begin() as c:
        c.exec_driver_sql("CREATE FUNCTION reject_publication_fixture() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            "IF (SELECT status FROM partitions WHERE id=NEW.partition_id) <> 'SUCCEEDED' THEN "
            "RAISE EXCEPTION 'fence did not execute' USING ERRCODE='P0001'; END IF; "
            "RAISE EXCEPTION 'fixture abort after fence' USING ERRCODE='23514'; END; $$")
        c.exec_driver_sql("CREATE TRIGGER reject_publication_fixture BEFORE INSERT ON accepted_results "
                          "FOR EACH ROW EXECUTE FUNCTION reject_publication_fixture()")
    try:
        response = complete(api, claimed, headers, body)
        assert response.status_code == 503 and response.json()["error"]["outcome"] == "not_committed"
        assert_unaccepted(api, claimed)
        assert events(api) == before_events
        with api.engine.connect() as c:
            assert c.scalar(sa.select(sa.func.count()).select_from(db.request_receipts).where(db.request_receipts.c.operation == "complete")) == 0
    finally:
        with api.admin_engine.begin() as c:
            c.exec_driver_sql("DROP TRIGGER reject_publication_fixture ON accepted_results")
            c.exec_driver_sql("DROP FUNCTION reject_publication_fixture()")
    assert complete(api, claimed, headers, body).status_code == 201


@contextmanager
def fenced_barrier(api):
    # Test-only SQL trigger in this disposable DB. No production hook/endpoint.
    key = int(uuid4().hex[:7], 16)
    with api.admin_engine.begin() as c:
        c.exec_driver_sql(f"CREATE FUNCTION publication_barrier_fixture() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            "IF (SELECT status FROM partitions WHERE id=NEW.partition_id) <> 'SUCCEEDED' THEN "
            "RAISE EXCEPTION 'fence did not execute'; END IF; "
            f"PERFORM pg_advisory_xact_lock({key}); RETURN NEW; END; $$")
        c.exec_driver_sql("CREATE TRIGGER publication_barrier_fixture BEFORE INSERT ON accepted_results "
                          "FOR EACH ROW EXECUTE FUNCTION publication_barrier_fixture()")
    gate = api.admin_engine.connect()
    gate.execute(sa.text("SELECT pg_advisory_lock(:key)"), {"key": key})
    try:
        yield gate, key
    finally:
        gate.execute(sa.text("SELECT pg_advisory_unlock(:key)"), {"key": key})
        gate.close()
        with api.admin_engine.begin() as c:
            c.exec_driver_sql("DROP TRIGGER publication_barrier_fixture ON accepted_results")
            c.exec_driver_sql("DROP FUNCTION publication_barrier_fixture()")


def wait_for_blocked(api, count):
    deadline = time.monotonic() + 1.5
    with api.admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        while time.monotonic() < deadline:
            rows = c.execute(sa.text("SELECT pid, wait_event FROM pg_stat_activity WHERE datname=:database "
                "AND usename='relay_runtime' AND wait_event_type='Lock'"), {"database": api.database}).mappings().all()
            if len(rows) >= count: return [dict(row) for row in rows]
            time.sleep(0.01)
    pytest.fail("Publication did not reach the deterministic database barrier")


def independent_complete(api, claimed, headers, body):
    with httpx.Client(base_url=api.url, trust_env=False, timeout=10) as client:
        return client.post(f"/v1/attempts/{claimed['attempt_id']}/complete", headers=headers, json=body)


def test_t05_concurrent_identical_complete_one_acceptance(api):
    claimed, headers, body = prepared(api)
    with fenced_barrier(api) as (gate, key):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(independent_complete, api, claimed, headers, body)
            wait_for_blocked(api, 1)
            second = pool.submit(independent_complete, api, claimed, headers, body | {"request_id": str(uuid4())})
            waiting = wait_for_blocked(api, 2)
            assert len({row["pid"] for row in waiting}) == 2
            gate.execute(sa.text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            responses = [first.result(timeout=10), second.result(timeout=10)]
    assert sorted(r.status_code for r in responses) == [200, 201]
    assert responses[0].json()["accepted_result"] == responses[1].json()["accepted_result"]
    before = accepted_rows(api)
    assert len(before) == 1
    assert [e["type"] for e in events(api)][-4:] == SUCCESS
    assert [e["type"] for e in events(api)].count("RESULT_ACCEPTED") == 1
    conflict = complete(api, claimed, headers, body | {"request_id": str(uuid4()), "sha256": "d"*64})
    assert conflict.status_code == 409 and accepted_rows(api) == before
    print("M1C T05", json.dumps({"blocked_backends": waiting, "statuses": [r.status_code for r in responses],
                                "accepted_result": responses[0].json()["accepted_result"]}, sort_keys=True))


def test_t26_valid_fence_commits_after_nominal_deadline(api):
    claimed, headers, body = prepared(api)
    with fenced_barrier(api) as (gate, key):
        deadline = shorten_lease(api, claimed, seconds=1.25)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(independent_complete, api, claimed, headers, body)
            waiting = wait_for_blocked(api, 1)
            # Barrier is reached only after the actual conditional mutation.
            with api.admin_engine.connect() as c:
                while c.scalar(sa.select(sa.func.clock_timestamp())) <= deadline:
                    time.sleep(0.01)
                release_time = c.scalar(sa.select(sa.func.clock_timestamp()))
            gate.execute(sa.text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            response = pending.result(timeout=10)
    assert response.status_code == 201, response.text
    sampled = datetime.fromisoformat(response.json()["accepted_result"]["accepted_at"])
    assert sampled < deadline < release_time
    assert len(accepted_rows(api)) == 1
    assert row_for(api, db.jobs, claimed["job_id"])["status"] == "SUCCEEDED"
    print("M1C T26", json.dumps({"accepted_at": sampled.isoformat(), "lease_expires_at": deadline.isoformat(),
        "barrier_released_at": release_time.isoformat(), "blocked_backends": waiting}, sort_keys=True))


def test_expiry_while_waiting_for_final_artifact_lock_uses_fresh_clock(api):
    claimed, headers, body = prepared(api)
    gate = api.admin_engine.connect()
    transaction = gate.begin()
    try:
        # The harness locks only artifact and never asks for earlier lock categories.
        gate.execute(sa.select(db.artifacts).where(db.artifacts.c.id == UUID(body["artifact_id"])).with_for_update())
        deadline = shorten_lease(api, claimed, seconds=1.25)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(independent_complete, api, claimed, headers, body)
            wait_for_blocked(api, 1)
            with api.admin_engine.connect() as c:
                while c.scalar(sa.select(sa.func.clock_timestamp())) <= deadline:
                    time.sleep(0.01)
            transaction.commit()
            response = pending.result(timeout=10)
        assert response.status_code == 409 and response.json()["error"]["code"] == "lease_expired"
        assert_unaccepted(api, claimed)
    finally:
        if transaction.is_active: transaction.rollback()
        gate.close()


def test_different_recorded_attempt_cannot_replace_accepted_partition(api):
    identity, _, rows = verified_input(api)
    job = submit_job(api, submission(identity, len(rows), split=[(0, 5), (5, len(rows)-5)])).json()["id"]
    _, _, headers = register(api)
    first_claim = claim(api, headers).json()
    data = output_bytes(rows[:5])
    reserved, _ = reserve_output(api, first_claim, headers, data)
    verified = api.client.put(reserved.json()["upload_url"], headers=headers, content=data).json()
    body = {k: first_claim[k] for k in ("job_id", "partition_id", "generation")} | {
        "request_id": str(uuid4()), "artifact_id": verified["id"], "artifact_uri": verified["artifact_uri"], "sha256": verified["sha256"]}
    assert complete(api, first_claim, headers, body).status_code == 201
    before = accepted_rows(api)
    other_claim = claim(api, headers).json()
    assert other_claim["attempt_id"] != first_claim["attempt_id"] and other_claim["job_id"] == job
    conflict = complete(api, other_claim, headers, body | {"request_id": str(uuid4())})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "result_conflict"
    assert accepted_rows(api) == before


@pytest.mark.parametrize("boundary", ["lease_expires_at", "hard_deadline_at"])
def test_fenced_sql_rejects_exact_deadline_equality(api, boundary):
    claimed, headers, body = prepared(api)
    artifact = row_for(api, db.artifacts, body["artifact_id"])
    with api.engine.begin() as c:
        for table, identity in ((db.jobs, claimed["job_id"]), (db.partitions, claimed["partition_id"]),
                                (db.attempts, claimed["attempt_id"]), (db.artifacts, body["artifact_id"])):
            c.execute(sa.select(table).where(table.c.id == UUID(identity)).with_for_update())
        t = c.scalar(sa.select(db.attempts.c[boundary]).where(db.attempts.c.id == UUID(claimed["attempt_id"])))
        affected = c.execute(FENCED_UPDATE, dict(job_id=UUID(claimed["job_id"]), partition_id=UUID(claimed["partition_id"]),
            attempt_id=UUID(claimed["attempt_id"]), generation=int(claimed["generation"]),
            worker=UUID(claimed["worker_session_id"]), artifact_id=UUID(body["artifact_id"]),
            object_version=artifact["object_version"], sha256=body["sha256"], size_bytes=artifact["verified_size_bytes"], t=t)).rowcount
        assert affected == 0
    assert_unaccepted(api, claimed)


def run_worker(api):
    env = {k:v for k,v in os.environ.items() if k.upper() in
           ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC", "PATHEXT", "USERPROFILE")}
    env["RELAY_WORKER_BOOTSTRAP_TOKEN"] = api.settings["RELAY_WORKER_BOOTSTRAP_TOKEN"]
    worker = subprocess.run([sys.executable, str(ROOT / "scripts/run_worker.py"), "--base-url", api.url, "--complete"],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert worker.returncode == 0, worker.stdout + worker.stderr
    trace = json.loads(worker.stdout)
    assert trace["phase"] == "ACCEPTED" and trace["worker_pid"] not in (os.getpid(), api.pid)
    assert trace["elapsed_seconds"] < 10
    for value in (api.settings["POSTGRES_RUNTIME_PASSWORD"], api.settings["S3_RUNTIME_SECRET_KEY"],
                  api.settings["RELAY_WORKER_BOOTSTRAP_TOKEN"]):
        absent = value not in worker.stdout + worker.stderr + api.log_path.read_text()
        assert absent, "Credential present in process output (redacted)"
    return trace


def test_t01_real_multi_partition_workers_accepted_outputs_and_full_oracle(api):
    rows = fixture_rows(36)
    identity, _, _ = verified_input(api, rows)
    slices = [(0, 9), (9, 13), (22, 14)]
    job = submit_job(api, submission(identity, len(rows), split=slices)).json()["id"]
    traces, decoded = [], []
    for ordinal, (start, count) in enumerate(slices):
        trace = run_worker(api)
        traces.append(trace)
        assert trace["job_id"] == job and trace["generation"] == "1"
        page = api.client.get(f"/v1/jobs/{job}/results?after_ordinal={ordinal-1}&limit=1", headers=api.operator).json()
        assert page["items"][0]["ordinal"] == ordinal
        manifest = page["items"][0]
        assert manifest["artifact_id"] == trace["artifact_id"] and manifest["object_version"] == trace["object_version"]
        content = api.client.get(manifest["content_url"], headers=api.operator)
        assert content.status_code == 200
        assert content.headers["X-Object-Version"] == trace["object_version"]
        assert hashlib.sha256(content.content).hexdigest() == manifest["sha256"]
        output = read_parquet(pa.BufferReader(content.content), OUTPUT_SCHEMA).to_pylist()
        expected, counters = serial_oracle(rows[start:start+count])
        assert output == expected and trace["counters"] == counters
        decoded.extend(output)
        assert page["partial_result_count"] == str(ordinal+1)
        assert page["complete"] == (ordinal == len(slices)-1)
    # Independent client-side reducer, with exact integer arithmetic.
    groups = {}
    for row in decoded:
        key = (row["customer_region"], row["category"], row["event_date"])
        totals = groups.setdefault(key, [0, 0, 0])
        for index, field in enumerate(("record_count", "quantity_sum", "amount_cents_sum")):
            totals[index] += row[field]
    reduced = [dict(customer_region=k[0], category=k[1], event_date=k[2], record_count=v[0],
                    quantity_sum=v[1], amount_cents_sum=v[2]) for k,v in sorted(groups.items())]
    assert reduced == serial_oracle(rows)[0]
    result = api.client.get(f"/v1/jobs/{job}/results", headers=api.operator).json()
    assert result["job_status"] == "SUCCEEDED" and result["complete"] and len(result["items"]) == 3
    assert [row["ordinal"] for row in result["items"]] == [0, 1, 2]
    page = api.client.get(f"/v1/jobs/{job}/results?limit=1", headers=api.operator).json()
    assert page["next_cursor"] == 0
    status = api.client.get(f"/v1/jobs/{job}", headers=api.operator).json()
    assert status["complete"] and status["partial_result_count"] == status["partition_count"] == "3"
    with api.engine.connect() as c:
        assert c.execute(sa.select(db.partitions.c.status)).scalars().all() == ["SUCCEEDED"]*3
        assert c.execute(sa.select(db.attempts.c.status)).scalars().all() == ["SUCCEEDED"]*3
    assert len({t["worker_pid"] for t in traces}) == 3
    assert len({t["worker_session_id"] for t in traces}) == 3
    assert len(accepted_rows(api)) == 3
    history = events(api)
    assert [e["seq"] for e in history] == list(range(1, len(history)+1))
    assert [e["type"] for e in history].count("RESULT_ACCEPTED") == 3
    assert [e["type"] for e in history].count("JOB_SUCCEEDED") == 1
    print("M1C T01", json.dumps({"input_id": identity, "job_id": job, "api_pid": api.pid,
        "database": api.database, "workers": traces,
        "results": result, "oracle_groups": len(reduced), "event_types": [e["type"] for e in history]}, sort_keys=True))


def test_result_read_pins_original_version_and_missing_version_is_integrity_failure(api):
    claimed, headers, body = prepared(api)
    assert complete(api, claimed, headers, body).status_code == 201
    before = accepted_rows(api)
    artifact = row_for(api, db.artifacts, body["artifact_id"])
    admin = api.storage[0]
    # Fresh test key only: trusted-admin newer version cannot be substituted.
    newer = admin.put_object(Bucket=artifact["bucket"], Key=artifact["object_key"], Body=b"not accepted parquet")
    assert newer["VersionId"] != artifact["object_version"]
    content = api.client.get(f"/v1/artifacts/{artifact['id']}/content", headers=api.operator)
    assert content.status_code == 200 and hashlib.sha256(content.content).hexdigest() == body["sha256"]
    assert content.headers["X-Object-Version"] == artifact["object_version"]
    # Deliberately remove ONLY this disposable fixture's exact pinned version.
    admin.delete_object(Bucket=artifact["bucket"], Key=artifact["object_key"], VersionId=artifact["object_version"])
    for path in (f"/v1/artifacts/{artifact['id']}/content", f"/v1/jobs/{claimed['job_id']}/results"):
        response = api.client.get(path, headers=api.operator)
        assert response.status_code == 422 and response.json()["error"]["code"] == "integrity_failure"
    assert accepted_rows(api) == before and row_for(api, db.artifacts, body["artifact_id"]) == artifact
    assert '"error_code": "integrity_failure"' in api.log_path.read_text()
