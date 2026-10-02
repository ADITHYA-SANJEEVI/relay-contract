import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa

from relay.control.common import Rejection, fingerprint, receipt, wire
from relay.control.leases import require_live
from relay.db import schema as db
from tests.integration.conftest import claim, register, submission, submit_job, verified_input
from tests.integration.test_m1b import active_claim, row_for
from tests.publication.test_m1c import (accepted_rows, complete, events, prepared, shorten_lease,
                                       wait_for_blocked)


def report(name, **values):
    print("M2 " + name, json.dumps(wire(values), sort_keys=True))


def renew(api, claimed, headers, sequence="1", **changes):
    body = {k: claimed[k] for k in ("job_id", "partition_id", "generation")} | {"sequence": sequence} | changes
    return api.client.post(f"/v1/attempts/{claimed['attempt_id']}/renew", headers=headers, json=body)


def worker_row(api, headers):
    with api.engine.connect() as c:
        row = c.execute(sa.select(db.workers).where(
            db.workers.c.session_id == UUID(headers["X-Worker-Session"]))).mappings().one()
        return {k: row[k] for k in ("session_id", "state", "last_seen_at", "last_heartbeat_seq", "stopped_at", "next_event_seq")}


def heartbeat(api, headers, sequence):
    return api.client.post(f"/v1/workers/{headers['X-Worker-Session']}/heartbeat", headers=headers,
                           json={"sequence": sequence})


def lifecycle(api, headers, action):
    return api.client.post(f"/v1/workers/{headers['X-Worker-Session']}/{action}", headers=headers, json={})


def cross_deadline(api, deadline):
    with api.admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        while True:
            now = c.scalar(sa.select(sa.func.clock_timestamp()))
            if now >= deadline: return now
            time.sleep(min(0.025, max(0.001, (deadline - now).total_seconds())))


def test_heartbeat_lifecycle_and_active_drain_publication(api):
    claimed, headers, body = prepared(api)
    original = row_for(api, db.attempts, claimed["attempt_id"])
    first = heartbeat(api, headers, "5")
    assert first.status_code == 200 and first.json()["applied"] and first.json()["liveness"] == "FRESH"
    seen = worker_row(api, headers)
    for sequence in ("5", "4", "0"):
        result = heartbeat(api, headers, sequence)
        assert result.status_code == 200 and not result.json()["applied"]
        assert worker_row(api, headers) == seen
    assert row_for(api, db.attempts, claimed["attempt_id"]) == original
    assert lifecycle(api, headers, "stop").status_code == 409
    draining = lifecycle(api, headers, "drain")
    assert draining.status_code == 200 and draining.json()["state"] == "DRAINING"
    assert lifecycle(api, headers, "drain").json() == draining.json()
    assert claim(api, headers).json()["error"]["code"] == "worker_draining"
    assert renew(api, claimed, headers).status_code == 200
    assert complete(api, claimed, headers, body).status_code == 201
    stopped = lifecycle(api, headers, "stop")
    assert stopped.status_code == 200 and stopped.json()["state"] == "STOPPED"
    assert lifecycle(api, headers, "stop").json() == stopped.json()
    assert lifecycle(api, headers, "drain").json() == stopped.json()
    assert claim(api, headers).status_code == 409
    assert heartbeat(api, headers, "6").json()["state"] == "STOPPED"
    with api.engine.connect() as c:
        history = c.execute(sa.select(db.worker_events).order_by(db.worker_events.c.seq)).mappings().all()
    assert [r["type"] for r in history] == ["WORKER_REGISTERED", "WORKER_DRAINING", "WORKER_STOPPED"]
    assert [r["seq"] for r in history] == [1, 2, 3]
    report("LIFECYCLE", heartbeat=first.json(), duplicate_seen=seen, stopped=stopped.json(), events=[dict(r) for r in history])


def test_idle_stop_and_suspect_telemetry(api):
    _, _, headers = register(api)
    with api.engine.begin() as c:
        c.execute(db.workers.update().where(db.workers.c.session_id == UUID(headers["X-Worker-Session"]))
            .values(last_seen_at=sa.func.clock_timestamp() - sa.text("interval '31 seconds'")))
    assert heartbeat(api, headers, "0").json()["liveness"] == "SUSPECT"
    assert heartbeat(api, headers, "1").json()["liveness"] == "FRESH"
    assert heartbeat(api, headers, "9223372036854775807").status_code == 200
    assert not heartbeat(api, headers, "2").json()["applied"]
    assert lifecycle(api, headers, "stop").status_code == 200
    with api.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.attempts)) == 0
        assert c.scalar(sa.select(sa.func.count()).select_from(db.worker_events)) == 2


@pytest.mark.parametrize("sequence", ["-1", "01", "9223372036854775808", "10000000000000000000", 1, True])
def test_bounded_telemetry_and_renewal_sequences(api, sequence):
    claimed, headers, _ = active_claim(api)
    before = row_for(api, db.attempts, claimed["attempt_id"])
    assert heartbeat(api, headers, sequence).status_code == 422
    assert renew(api, claimed, headers, sequence).status_code == 422
    assert row_for(api, db.attempts, claimed["attempt_id"]) == before


def test_renew_sequence_timeline_conflict_and_expired_duplicate(api):
    claimed, headers, _ = active_claim(api)
    original = row_for(api, db.attempts, claimed["attempt_id"])
    first = renew(api, claimed, headers, "2")
    assert first.status_code == 200, first.text
    result = first.json()
    assert datetime.fromisoformat(result["lease_expires_at"]) == datetime.fromisoformat(result["db_time"]) + timedelta(seconds=30)
    assert datetime.fromisoformat(result["lease_expires_at"]) > original["lease_expires_at"]
    after = row_for(api, db.attempts, claimed["attempt_id"])
    assert after["last_renew_response"] == result and after["last_renew_seq"] == 2
    assert renew(api, claimed, headers, "2").json() == result
    lower = renew(api, claimed, headers, "1")
    assert not lower.json()["applied"] and lower.json()["lease_expires_at"] == result["lease_expires_at"]
    conflict = renew(api, claimed, headers, "2", generation="2")
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"
    assert row_for(api, db.attempts, claimed["attempt_id"]) == after
    second = renew(api, claimed, headers, "3")
    assert second.status_code == 200 and second.json()["lease_expires_at"] > result["lease_expires_at"]
    assert row_for(api, db.attempts, claimed["attempt_id"])["hard_deadline_at"] == original["hard_deadline_at"]
    assert [e["type"] for e in events(api)].count("LEASE_RENEWED") == 2
    expired = shorten_lease(api, claimed, expired=True)
    before = row_for(api, db.attempts, claimed["attempt_id"])
    for seq in ("3", "4", "1"):
        response = renew(api, claimed, headers, seq)
        assert response.status_code == 409 and response.json()["error"]["code"] == "lease_expired"
    assert heartbeat(api, headers, "9").status_code == 200
    assert lifecycle(api, headers, "stop").status_code == 409  # ACTIVE is unsettled, even when expired.
    assert row_for(api, db.attempts, claimed["attempt_id"]) == before
    logs = [json.loads(line) for line in api.log_path.read_text(encoding="utf-8").splitlines() if line.startswith("{")]
    assert {entry.get("outcome") for entry in logs if entry.get("operation") == "renew"} >= {"applied", "ignored", "rejected"}
    report("RENEW_TIMELINE", original_lease=original["lease_expires_at"], first=result, lower=lower.json(), second=second.json(), expired=expired)


def test_concurrent_latest_renew_one_event_and_cached_result(api):
    claimed, headers, _ = active_claim(api)
    body = {k: claimed[k] for k in ("job_id", "partition_id", "generation")} | {"sequence": "1"}
    with httpx.Client(base_url=api.url, trust_env=False) as a, httpx.Client(base_url=api.url, trust_env=False) as b:
        with api.admin_engine.connect() as gate:
            transaction = gate.begin()
            gate.execute(sa.select(db.jobs).where(db.jobs.c.id == UUID(claimed["job_id"])).with_for_update())
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(client.post, f"/v1/attempts/{claimed['attempt_id']}/renew", headers=headers, json=body) for client in (a, b)]
                try: waiting = wait_for_blocked(api, 2)
                finally: transaction.commit()
                responses = [future.result(timeout=10) for future in futures]
    assert all(response.status_code == 200 for response in responses)
    assert responses[0].json() == responses[1].json()
    history = [e for e in events(api) if e["type"] == "LEASE_RENEWED"]
    assert len(history) == 1 and history[0]["occurred_at"].isoformat() == responses[0].json()["db_time"]
    attempt = row_for(api, db.attempts, claimed["attempt_id"])
    assert attempt["last_renew_seq"] == 1 and attempt["last_renew_response"] == responses[0].json()
    report("CONCURRENT_RENEW", waiting_backends=waiting, response=responses[0].json(), renewal_events=1)


def test_renew_identity_auth_and_atomic_abort(api):
    claimed, headers, _ = active_claim(api)
    _, _, other = register(api)
    assert renew(api, claimed, other).status_code == 403
    assert renew(api, claimed, headers, generation="2").status_code == 409
    assert renew(api, claimed, headers, extra=True).status_code == 422
    assert api.client.post(f"/v1/attempts/{claimed['attempt_id']}/renew", json={}).status_code == 401
    for action in ("heartbeat", "drain", "stop"):
        assert api.client.post(f"/v1/workers/{headers['X-Worker-Session']}/{action}", headers=other,
                              json={"sequence": "1"} if action == "heartbeat" else {}).status_code == 403
    before = row_for(api, db.attempts, claimed["attempt_id"])
    with api.admin_engine.begin() as c:
        c.execute(sa.text("ALTER TABLE events ADD CONSTRAINT test_abort_renew CHECK (type <> 'LEASE_RENEWED')"))
    try:
        response = renew(api, claimed, headers)
        assert response.status_code == 503 and response.json()["error"]["outcome"] == "not_committed"
        assert row_for(api, db.attempts, claimed["attempt_id"]) == before
        assert [e["type"] for e in events(api)].count("LEASE_RENEWED") == 0
    finally:
        with api.admin_engine.begin() as c:
            c.execute(sa.text("ALTER TABLE events DROP CONSTRAINT test_abort_renew"))
    assert renew(api, claimed, headers).status_code == 200
    assert renew(api, claimed, headers, "9223372036854775807").status_code == 200


@pytest.mark.parametrize("lock_name", ["job", "partition", "attempt"])
def test_t16_authoritative_lock_wait_crosses_deadline(api, lock_name):
    claimed, headers, _ = active_claim(api)
    deadline = shorten_lease(api, claimed, seconds=1.25)
    body = {k: claimed[k] for k in ("job_id", "partition_id", "generation")} | {"sequence": "1"}
    with httpx.Client(base_url=api.url, trust_env=False, timeout=10) as client:
        with api.admin_engine.connect() as gate:
            transaction = gate.begin()
            table = {"job": db.jobs, "partition": db.partitions, "attempt": db.attempts}[lock_name]
            gate.execute(sa.select(table).where(table.c.id == UUID(claimed[lock_name + "_id"])).with_for_update())
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(client.post, f"/v1/attempts/{claimed['attempt_id']}/renew", headers=headers, json=body)
                waiting = wait_for_blocked(api, 1)
                with api.admin_engine.connect() as c:
                    entered = c.scalar(sa.select(sa.func.clock_timestamp()))
                assert entered < deadline
                released = cross_deadline(api, deadline)
                transaction.commit()
                response = future.result(timeout=10)
    assert response.status_code == 409 and response.json()["error"]["code"] == "lease_expired"
    attempt = row_for(api, db.attempts, claimed["attempt_id"])
    assert attempt["last_renew_seq"] == 0 and attempt["lease_expires_at"] == deadline and attempt["status"] == "ACTIVE"
    assert not any(e["type"] == "LEASE_RENEWED" for e in events(api))
    report("FINAL_LOCK_EXPIRY" if lock_name == "attempt" else "LOCK_EXPIRY", lock=lock_name,
        waiting_backends=waiting, entered=entered, deadline=deadline, release=released, status=response.status_code)


@pytest.mark.parametrize("boundary", ["lease_expires_at", "hard_deadline_at"])
def test_t16_exact_boundary_canonical_predicate(api, boundary):
    claimed, headers, _ = active_claim(api)
    with api.engine.begin() as c:
        job = dict(c.execute(sa.select(db.jobs).where(db.jobs.c.id == UUID(claimed["job_id"])).with_for_update()).mappings().one())
        partition = dict(c.execute(sa.select(db.partitions).where(db.partitions.c.id == UUID(claimed["partition_id"])).with_for_update()).mappings().one())
        attempt = dict(c.execute(sa.select(db.attempts).where(db.attempts.c.id == UUID(claimed["attempt_id"])).with_for_update()).mappings().one())
        # Exact microsecond boundary supplied to the production predicate, using actual DB rows.
        with pytest.raises(Rejection) as error:
            require_live(job, partition, attempt, UUID(headers["X-Worker-Session"]), 1, attempt[boundary])
        assert error.value.code == "lease_expired"
        assert c.scalar(sa.select((sa.literal(attempt[boundary]) < db.attempts.c[boundary])).where(
            db.attempts.c.id == attempt["id"])) is False


def test_hard_deadline_cap_and_actual_expiry_no_bypass(api):
    identity, _, rows = verified_input(api)
    submitted = submit_job(api, submission(identity, len(rows)) | {"policy": {"lease_seconds": 60, "max_attempt_seconds": 60}})
    assert submitted.status_code == 201
    _, _, headers = register(api)
    key = str(uuid4()); claimed = claim(api, headers, key).json()
    from tests.integration.test_m1b import output_bytes, reserve_output
    data = output_bytes(rows)
    reserved, _ = reserve_output(api, claimed, headers, data)
    verified = api.client.put(reserved.json()["upload_url"], headers=headers, content=data).json()
    timeline = []
    hard = datetime.fromisoformat(claimed["hard_deadline_at"])
    for sequence in ("1", "2", "3"):
        if sequence == "3":
            cross_deadline(api, hard - timedelta(seconds=1.5))
        response = renew(api, claimed, headers, sequence)
        assert response.status_code == 200
        assert response.json()["lease_expires_at"] == claimed["hard_deadline_at"]
        timeline.append(response.json())
    # Real 60-second minimum lifetime; no claim/hard-deadline edits or guard bypass.
    crossed = cross_deadline(api, hard)
    for sequence in ("3", "4", "2"):
        response = renew(api, claimed, headers, sequence)
        assert response.status_code == 409 and response.json()["error"]["code"] == "lease_expired"
    assert heartbeat(api, headers, "100").status_code == 200
    replay = claim(api, headers, key).json()
    assert replay == claimed | {"replay": True}
    publication = complete(api, claimed, headers, {k: claimed[k] for k in ("job_id", "partition_id", "generation")} | {
        "request_id": str(uuid4()), "artifact_id": verified["id"], "artifact_uri": verified["artifact_uri"], "sha256": verified["sha256"]})
    assert publication.status_code == 409 and publication.json()["error"]["code"] == "lease_expired"
    assert accepted_rows(api) == []
    attempt = row_for(api, db.attempts, claimed["attempt_id"])
    assert attempt["hard_deadline_at"] == hard and attempt["status"] == "ACTIVE" and attempt["last_renew_seq"] == 3
    report("HARD_CAP", claim=claimed, renewals=timeline, crossed=crossed, artifact_status=verified["status"], publication_status=publication.status_code)


def race_claims(api, participants):
    # Independent clients already constructed: DB barrier gates real HTTP requests.
    with api.admin_engine.connect() as gate:
        transaction = gate.begin()
        gate.execute(sa.select(db.scheduler_state).with_for_update())
        with ThreadPoolExecutor(max_workers=len(participants)) as pool:
            started = time.monotonic()
            futures = [pool.submit(client.post, f"/v1/workers/{headers['X-Worker-Session']}/claim",
                headers=headers | {"Idempotency-Key": key}, json={}) for client, headers, key in participants]
            try:
                waiting = wait_for_blocked(api, min(2, len(participants)))
            finally:
                transaction.commit()
            responses = [f.result(timeout=15) for f in futures]
            elapsed = time.monotonic() - started
    return responses, waiting, elapsed


def test_t06_same_key_concurrent_scope_and_busy(api):
    identity, _, rows = verified_input(api)
    assert submit_job(api, submission(identity, len(rows), split=[(0, 6), (6, 6)])).status_code == 201
    _, _, headers = register(api)
    key = str(uuid4())
    with httpx.Client(base_url=api.url, trust_env=False) as a, httpx.Client(base_url=api.url, trust_env=False) as b:
        responses, waiting, elapsed = race_claims(api, [(a, headers, key), (b, headers, key)])
    assert sorted(r.status_code for r in responses) == [200, 201]
    original = next(r.json() for r in responses if r.status_code == 201)
    replay = next(r.json() for r in responses if r.status_code == 200)
    assert replay == original | {"replay": True}
    assert claim(api, headers, key).json() == replay
    assert claim(api, headers).json()["error"]["code"] == "worker_busy"
    assert api.client.post(f"/v1/workers/{headers['X-Worker-Session']}/claim",
        headers=headers | {"Idempotency-Key": key}, json={"invented": True}).status_code == 422
    with api.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.attempts)) == 1
        assert c.scalar(sa.select(sa.func.count()).select_from(db.request_receipts).where(db.request_receipts.c.operation == "claim")) == 1
    assert [e["type"] for e in events(api)].count("ATTEMPT_CLAIMED") == 1
    _, _, other = register(api)
    second = claim(api, other, key)
    assert second.status_code == 201 and second.json()["attempt_id"] != original["attempt_id"]
    with api.engine.connect() as c:
        receipts = [dict(r) for r in c.execute(sa.select(db.request_receipts).where(db.request_receipts.c.operation == "claim")).mappings()]
        assert len(receipts) == 2 and all(r["request_hash"] == fingerprint({}) and r["key"] == key for r in receipts)
        assert len({r["scope"] for r in receipts}) == 2
        with pytest.raises(Rejection) as error:
            receipt(c, f"worker:{headers['X-Worker-Session']}:claim", key, "f" * 64)
        assert error.value.code == "idempotency_conflict"
        assert c.scalar(sa.select(sa.func.count()).select_from(db.attempts)) == 2
    assert [e["type"] for e in events(api)].count("ATTEMPT_CLAIMED") == 2
    report("T06", original=original, replay=replay, scopes=[r["scope"] for r in receipts], request_hash=fingerprint({}), waiting=waiting, elapsed_seconds=elapsed)


def test_t12_32_workers_one_partition(api):
    identity, _, rows = verified_input(api)
    assert submit_job(api, submission(identity, len(rows))).status_code == 201
    workers = []
    for index in range(32):
        response, _, headers = register(api, display_name=f"race-{index}")
        assert response.status_code == 201
        workers.append(headers)
    assert register(api)[0].status_code == 429
    clients = [httpx.Client(base_url=api.url, timeout=15, trust_env=False) for _ in workers]
    try:
        responses, waiting, elapsed = race_claims(api, [(client, h, str(uuid4())) for client, h in zip(clients, workers)])
    finally:
        for client in clients: client.close()
    assert sum(r.status_code == 201 for r in responses) == 1
    assert all(r.status_code in (201, 204, 503) for r in responses)
    for response in responses:
        if response.status_code == 503:
            assert response.json()["error"]["outcome"] == "not_committed"
    with api.engine.connect() as c:
        attempts = [dict(r) for r in c.execute(sa.select(db.attempts)).mappings()]
        partitions = [dict(r) for r in c.execute(sa.select(db.partitions)).mappings()]
        receipts = c.scalar(sa.select(sa.func.count()).select_from(db.request_receipts).where(db.request_receipts.c.operation == "claim"))
        scheduler = c.scalar(sa.select(db.scheduler_state.c.next_ticket))
        for column in (db.attempts.c.worker_session_id, db.attempts.c.partition_id):
            assert c.execute(sa.select(column).where(db.attempts.c.status == "ACTIVE").group_by(column)
                             .having(sa.func.count() > 1)).first() is None
    assert len(attempts) == 1 and attempts[0]["status"] == "ACTIVE" and attempts[0]["generation"] == 1
    assert len(partitions) == 1 and partitions[0]["status"] == "RUNNING" and partitions[0]["generation"] == 1
    assert receipts == sum(r.status_code in (201, 204) for r in responses) and scheduler == 3
    history = events(api)
    assert [e["seq"] for e in history] == [1, 2, 3, 4]
    assert [e["type"] for e in history] == ["JOB_SUBMITTED", "ATTEMPT_CLAIMED", "PARTITION_RUNNING", "JOB_RUNNING"]
    report("T12", sessions=32, statuses={str(s): sum(r.status_code == s for r in responses) for s in (201, 204, 503)},
        waiting_backends=waiting, generation=partitions[0]["generation"], owner=attempts[0]["worker_session_id"],
        receipts=receipts, scheduler_next_ticket=scheduler, diagnostic_elapsed_seconds=round(elapsed, 3))
