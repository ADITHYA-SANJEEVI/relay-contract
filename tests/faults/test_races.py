from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import UUID

import pytest
import sqlalchemy as sa

from relay.db import schema as db
from relay.recovery.service import discover, expire
from tests.concurrency.test_m2 import cross_deadline
from tests.integration.test_m1b import row_for
from tests.publication.test_m1c import (complete, events, fenced_barrier, independent_complete,
                                      prepared, shorten_lease, wait_for_blocked)
from .helpers import (assert_backoff, attempt_barrier, fail_http, failure_body, independent_post,
                      release, report, target_results)


def test_t23_renewal_wins_before_expired_discovery_recovery_rechecks(api):
    claimed, owner, _ = prepared(api)
    with attempt_barrier(api, "NEW.last_renew_seq > OLD.last_renew_seq") as (gate, key):
        deadline = shorten_lease(api, claimed, seconds=1.25)
        with ThreadPoolExecutor(max_workers=2) as pool:
            renewing = pool.submit(independent_post, api, f"/v1/attempts/{claimed['attempt_id']}/renew", owner,
                {k: claimed[k] for k in ("job_id", "partition_id", "generation")} | {"sequence": "1"})
            wait_for_blocked(api, 1)
            discovered_at = cross_deadline(api, deadline)
            # MVCC still exposes the old expired lease while the live renewal
            # holds locks at its update barrier. Recovery really discovers it.
            candidates = discover(api.engine)
            assert len(candidates) == 1
            recovering = pool.submit(expire, api.engine, candidates[0])
            waiting = wait_for_blocked(api, 2)
            release(gate, key)
            renewal, recovery = renewing.result(timeout=10), recovering.result(timeout=10)
    assert renewal.status_code == 200, renewal.text
    assert datetime.fromisoformat(renewal.json()["db_time"]) < deadline <= discovered_at
    assert recovery["outcome"] == "noop" and recovery["reason"] == "still_live"
    assert datetime.fromisoformat(recovery["db_time"]) < datetime.fromisoformat(renewal.json()["lease_expires_at"])
    assert row_for(api, db.attempts, claimed["attempt_id"])["status"] == "ACTIVE"
    assert [e["type"] for e in events(api)].count("LEASE_RENEWED") == 1
    assert not any(e["type"] == "ATTEMPT_EXPIRED" for e in events(api))
    report("T23_RENEW_FIRST", old_deadline=deadline, discovered_at=discovered_at, renewal=renewal.json(), recovery=recovery, waiters=waiting)


def test_t23_recovery_wins_delayed_renewal_cannot_resurrect(api):
    claimed, owner, _ = prepared(api)
    shorten_lease(api, claimed, expired=True)
    candidates = discover(api.engine)
    with attempt_barrier(api, "OLD.status='ACTIVE' AND NEW.status='EXPIRED'") as (gate, key):
        with ThreadPoolExecutor(max_workers=2) as pool:
            recovering = pool.submit(expire, api.engine, candidates[0])
            wait_for_blocked(api, 1)
            renewing = pool.submit(independent_post, api, f"/v1/attempts/{claimed['attempt_id']}/renew", owner,
                {k: claimed[k] for k in ("job_id", "partition_id", "generation")} | {"sequence": "1"})
            waiting = wait_for_blocked(api, 2)
            release(gate, key)
            recovery, renewal = recovering.result(timeout=10), renewing.result(timeout=10)
    assert recovery["outcome"] == "expired" and renewal.status_code == 409
    assert renewal.json()["error"]["code"] == "lease_expired"
    assert row_for(api, db.attempts, claimed["attempt_id"])["last_renew_seq"] == 0
    assert not any(e["type"] == "LEASE_RENEWED" for e in events(api))
    backoff = assert_backoff(api, claimed)
    report("T23_RECOVERY_FIRST", recovery=recovery, renewal_code=renewal.json()["error"]["code"], backoff=backoff, waiters=waiting)


@pytest.mark.parametrize("winner", ["publication", "failure"])
def test_t23_failure_publication_exactly_one_terminal_disposition(api, winner):
    claimed, owner, body = prepared(api)
    verified_before = row_for(api, db.artifacts, body["artifact_id"])
    fail_body = failure_body(claimed)
    barrier = fenced_barrier(api) if winner == "publication" else attempt_barrier(api, "OLD.status='ACTIVE' AND NEW.status='FAILED'")
    with barrier as (gate, key):
        with ThreadPoolExecutor(max_workers=2) as pool:
            def submit_failure():
                return pool.submit(independent_post, api, f"/v1/attempts/{claimed['attempt_id']}/fail", owner, fail_body)
            def submit_publication():
                return pool.submit(independent_complete, api, claimed, owner, body)
            first = submit_publication() if winner == "publication" else submit_failure()
            wait_for_blocked(api, 1)
            second = submit_failure() if winner == "publication" else submit_publication()
            waiting = wait_for_blocked(api, 2)
            release(gate, key)
            first_response, second_response = first.result(timeout=10), second.result(timeout=10)
    assert first_response.status_code == (201 if winner == "publication" else 200), first_response.text
    assert second_response.status_code == 409, second_response.text
    attempt = row_for(api, db.attempts, claimed["attempt_id"])
    assert attempt["status"] == ("SUCCEEDED" if winner == "publication" else "FAILED")
    results = target_results(api, claimed["partition_id"])
    assert len(results) == (1 if winner == "publication" else 0)
    types = [e["type"] for e in events(api)]
    assert types.count("RESULT_ACCEPTED") == (1 if winner == "publication" else 0)
    assert types.count("PARTITION_READY") == (0 if winner == "publication" else 1)
    if winner == "failure": assert_backoff(api, claimed)
    assert not (results and attempt["status"] == "FAILED")
    assert row_for(api, db.artifacts, body["artifact_id"]) == verified_before
    if winner == "failure":
        assert api.client.get(f"/v1/jobs/{claimed['job_id']}/results", headers=api.operator).json()["items"] == []
        assert api.client.get(f"/v1/artifacts/{body['artifact_id']}/content", headers=api.operator).status_code == 404
    report("T23_FAIL_PUBLISH", winner=winner, statuses=[first_response.status_code, second_response.status_code],
           loser_code=second_response.json()["error"]["code"], attempt=attempt, accepted=results, event_types=types, waiters=waiting)


def test_failure_post_final_attempt_lock_time_expired_owner_and_wrong_owner(api):
    claimed, owner, _ = prepared(api)
    from .helpers import new_owner
    assert fail_http(api, claimed, new_owner(api)).status_code == 403
    before = events(api)
    deadline = shorten_lease(api, claimed, seconds=1.25)
    gate = api.admin_engine.connect()
    transaction = gate.begin()
    try:
        gate.execute(sa.select(db.attempts).where(db.attempts.c.id == UUID(claimed["attempt_id"])).with_for_update())
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(independent_post, api, f"/v1/attempts/{claimed['attempt_id']}/fail", owner, failure_body(claimed))
            waiting = wait_for_blocked(api, 1)
            released_at = cross_deadline(api, deadline)
            transaction.commit()
            response = future.result(timeout=10)
        assert response.status_code == 409 and response.json()["error"]["code"] == "lease_expired"
        assert events(api) == before
        assert row_for(api, db.attempts, claimed["attempt_id"])["status"] == "ACTIVE"
        report("FAILURE_POST_LOCK", deadline=deadline, released_at=released_at, waiters=waiting, code=response.json()["error"]["code"])
    finally:
        if transaction.is_active: transaction.rollback()
        gate.close()


def test_t26_valid_publication_fence_blocks_recovery_past_deadline(api):
    claimed, owner, body = prepared(api)
    with fenced_barrier(api) as (gate, key):
        deadline = shorten_lease(api, claimed, seconds=1.25)
        with ThreadPoolExecutor(max_workers=2) as pool:
            publishing = pool.submit(independent_complete, api, claimed, owner, body)
            wait_for_blocked(api, 1)
            crossed = cross_deadline(api, deadline)
            candidates = discover(api.engine)
            assert len(candidates) == 1
            recovering = pool.submit(expire, api.engine, candidates[0])
            waiting = wait_for_blocked(api, 2)
            release(gate, key)
            publication, recovery = publishing.result(timeout=10), recovering.result(timeout=10)
    assert publication.status_code == 201, publication.text
    assert datetime.fromisoformat(publication.json()["accepted_result"]["accepted_at"]) < deadline <= crossed
    assert recovery["outcome"] == "noop" and recovery["reason"] == "already_settled_or_superseded"
    assert row_for(api, db.attempts, claimed["attempt_id"])["status"] == "SUCCEEDED"
    assert len(target_results(api, claimed["partition_id"])) == 1
    assert not any(e["type"] in ("ATTEMPT_EXPIRED", "PARTITION_READY") for e in events(api))
    report("T26_RECOVERY", publication=publication.json(), deadline=deadline, crossed=crossed,
           recovery=recovery, waiters=waiting)
