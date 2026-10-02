import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import UUID

import pytest
import sqlalchemy as sa

from relay.db import schema as db
from relay.recovery.service import discover, expire, run_batch
from tests.integration.conftest import claim
from tests.integration.test_m1b import row_for
from tests.publication.test_m1c import complete, events, shorten_lease, wait_for_blocked, run_worker
from .helpers import (Processes, advance_eligibility, assert_backoff, attempt_barrier, attempt_history,
    fail_http, failure_body, fresh_claim, new_job, new_owner, release, report, target_results, verify_output)


@pytest.mark.parametrize("code,retryable", [
    ("worker_crash", True), ("store_transient", True), ("transport_error", True),
    ("input_invalid", False), ("schema_mismatch", False), ("workload_validation", False), ("integer_overflow", False)])
def test_failure_classification_duplicate_and_bounds(api, code, retryable):
    new_job(api)
    owner = new_owner(api)
    claimed = fresh_claim(api, owner, 1)
    body = failure_body(claimed, code, {"phase": "execution"})
    before = events(api)
    for invalid in (body | {"retryable": True}, body | {"code": "untrusted"}, body | {"detail": {"x": "a" * 4097}},
                    body | {"detail": []}, body | {"generation": True}):
        assert fail_http(api, claimed, owner, invalid).status_code == 422
    assert events(api) == before
    first = fail_http(api, claimed, owner, body)
    assert first.status_code == 200, first.text
    response = first.json()
    assert response["partition_status"] == ("READY" if retryable else "FAILED")
    attempt = row_for(api, db.attempts, claimed["attempt_id"])
    assert attempt["status"] == "FAILED" and attempt["failure_detail"] == body["detail"] and attempt["failure_fingerprint"]
    after = events(api)
    assert fail_http(api, claimed, owner, body).json() == response
    assert fail_http(api, claimed, owner, body | {"detail": {"changed": True}}).status_code == 409
    assert events(api) == after
    assert [e["type"] for e in after[len(before):]] == ["ATTEMPT_FAILED", "PARTITION_READY" if retryable else "PARTITION_FAILED"] + ([] if retryable else ["JOB_FAILED"])
    assert row_for(api, db.jobs, claimed["job_id"])["status"] == ("RUNNING" if retryable else "FAILED")
    if retryable: assert_backoff(api, claimed)
    assert target_results(api, claimed["partition_id"]) == []
    report("FAILURE_CODE", code=code, retryable=retryable, response=response)


def test_duplicate_failure_remains_historical_after_next_claim(api):
    new_job(api)
    owner = new_owner(api)
    old = fresh_claim(api, owner, 1)
    body = failure_body(old)
    first = fail_http(api, old, owner, body)
    assert first.status_code == 200
    original = row_for(api, db.attempts, old["attempt_id"])
    trace = advance_eligibility(api, old)
    current = fresh_claim(api, new_owner(api), 2)
    before = row_for(api, db.partitions, current["partition_id"]), events(api)
    assert fail_http(api, old, owner, body).json() == first.json()
    assert fail_http(api, old, owner, body | {"generation": "2"}).status_code == 409
    assert row_for(api, db.attempts, old["attempt_id"]) == original
    assert (row_for(api, db.partitions, current["partition_id"]), events(api)) == before
    report("FAILURE_HISTORICAL", original=first.json(), backoff=trace, latest_attempt=current["attempt_id"], generation=2)


def test_t09_exact_budget_drains_healthy_work_before_job_failure(api):
    job, _ = new_job(api, maximum=3, partitions=2)
    owner = new_owner(api)
    trace = []
    for generation in range(1, 4):
        claimed = fresh_claim(api, owner, generation)
        assert claimed["ordinal"] == 0
        response = fail_http(api, claimed, owner)
        assert response.status_code == 200, response.text
        trace.append(response.json())
        if generation < 3:
            # Other healthy work can run while this partition backs off; don't
            # poll here and accidentally claim it. Eligibility bypass is test-only.
            trace[-1]["backoff"] = advance_eligibility(api, claimed)
        else:
            assert row_for(api, db.partitions, claimed["partition_id"])["status"] == "FAILED"
            assert row_for(api, db.jobs, job)["status"] == "RUNNING"
            before = events(api)
            assert fail_http(api, claimed, owner).json() == response.json()
            assert events(api) == before
    history = attempt_history(api, claimed["partition_id"])
    assert [a["generation"] for a in history] == [1, 2, 3] and all(a["status"] == "FAILED" for a in history)
    healthy = run_worker(api)
    assert healthy["job_id"] == job and healthy["generation"] == "1" and healthy["job_status"] == "FAILED"
    assert row_for(api, db.jobs, job)["status"] == "FAILED" and claim(api, owner).status_code == 204
    assert [e["type"] for e in events(api)].count("ATTEMPT_CLAIMED") == 4  # Three target + one healthy.
    assert [e["type"] for e in events(api)][-4:] == ["ATTEMPT_SUCCEEDED", "PARTITION_SUCCEEDED", "RESULT_ACCEPTED", "JOB_FAILED"]
    with api.engine.connect() as c:
        assert c.scalar(sa.select(sa.func.count()).select_from(db.attempts).where(db.attempts.c.status == "ACTIVE")) == 0
    report("T09", job_id=job, target_history=history, dispositions=trace, healthy_result=healthy["accepted_result"],
           event_types=[e["type"] for e in events(api)])


def test_backoff_all_generations_and_expiry_budget_no_extra_claim(api):
    new_job(api, maximum=10)
    owner = new_owner(api)
    processes = Processes(api)
    trace = []
    try:
        for generation in range(1, 11):
            claimed = fresh_claim(api, owner, generation)
            shorten_lease(api, claimed, expired=True)
            recovery = processes.recover_once()
            assert row_for(api, db.attempts, claimed["attempt_id"])["status"] == "EXPIRED"
            if generation < 10:
                backoff = assert_backoff(api, claimed)
                # At g6+ the real 30s backoff must deny fresh claim before bypass.
                if generation >= 6: assert claim(api, owner).status_code == 204
                advance_eligibility(api, claimed)
                trace.append(backoff)
            else:
                assert row_for(api, db.jobs, claimed["job_id"])["status"] == "FAILED"
                assert row_for(api, db.partitions, claimed["partition_id"])["status"] == "FAILED"
                assert claim(api, owner).status_code == 204
            assert any(line.get("outcome") == "expired" for line in recovery)
        history = attempt_history(api, claimed["partition_id"])
        assert [a["generation"] for a in history] == list(range(1, 11))
        assert all(a["status"] == "EXPIRED" for a in history)
        assert [e["type"] for e in events(api)].count("ATTEMPT_EXPIRED") == 10
        assert [e["type"] for e in events(api)].count("PARTITION_READY") == 9
        report("BACKOFF_CAP", backoffs=trace, final_history=history)
    finally: processes.close()


def test_failed_partition_does_not_revoke_other_running_owner(api):
    job, rows = new_job(api, partitions=2)
    poison_owner, healthy_owner = new_owner(api), new_owner(api)
    poison = fresh_claim(api, poison_owner, 1)
    healthy = fresh_claim(api, healthy_owner, 1)
    assert healthy["ordinal"] == 1
    assert fail_http(api, poison, poison_owner, failure_body(poison, "input_invalid")).status_code == 200
    assert row_for(api, db.jobs, job)["status"] == "RUNNING"
    assert row_for(api, db.attempts, healthy["attempt_id"])["status"] == "ACTIVE"
    from tests.concurrency.test_m2 import renew
    assert renew(api, healthy, healthy_owner).status_code == 200
    body, _ = verify_output(api, healthy, healthy_owner, rows[12:])
    response = complete(api, healthy, healthy_owner, body)
    assert response.status_code == 201 and response.json()["job_status"] == "FAILED"
    assert [e["type"] for e in events(api)][-4:] == ["ATTEMPT_SUCCEEDED", "PARTITION_SUCCEEDED", "RESULT_ACCEPTED", "JOB_FAILED"]
    report("DRAIN_RUNNING", job_id=job, failed_attempt=poison["attempt_id"], accepted=response.json()["accepted_result"])


def test_real_hard_deadline_expiry_exhaustion_keeps_verified_orphan(api):
    new_job(api, maximum=1, lease=60)
    owner = new_owner(api)
    claimed = fresh_claim(api, owner, 1)
    _, artifact = verify_output(api, claimed, owner, [])
    before = row_for(api, db.artifacts, artifact["id"])
    assert claimed["lease_expires_at"] == claimed["hard_deadline_at"]
    from tests.concurrency.test_m2 import cross_deadline
    crossed = cross_deadline(api, datetime.fromisoformat(claimed["hard_deadline_at"]))
    processes = Processes(api)
    try:
        recovery = processes.recover_once()
        attempt = row_for(api, db.attempts, claimed["attempt_id"])
        assert attempt["status"] == "EXPIRED" and attempt["failure_code"] == "hard_deadline_exceeded"
        assert attempt["claimed_at"] == datetime.fromisoformat(claimed["claimed_at"])
        assert attempt["hard_deadline_at"] == datetime.fromisoformat(claimed["hard_deadline_at"])
        assert row_for(api, db.partitions, claimed["partition_id"])["status"] == "FAILED"
        assert row_for(api, db.jobs, claimed["job_id"])["status"] == "FAILED"
        assert row_for(api, db.artifacts, artifact["id"]) == before
        assert target_results(api, claimed["partition_id"]) == [] and claim(api, owner).status_code == 204
        assert [e["type"] for e in events(api)][-3:] == ["ATTEMPT_EXPIRED", "PARTITION_FAILED", "JOB_FAILED"]
        report("HARD_EXPIRY", claim=claimed, crossed=crossed, recovery=recovery, attempt=attempt, orphan=before)
    finally: processes.close()


def test_competing_recovery_instances_and_restart(api):
    new_job(api)
    claimed = fresh_claim(api, new_owner(api), 1)
    processes = Processes(api)
    try:
        with attempt_barrier(api, "OLD.status='ACTIVE' AND NEW.status='EXPIRED'") as (gate, key):
            # Boot both actual loops BEFORE expiry. Startup time must not consume
            # the production 2s lock timeout or the lock-observer deadline.
            first = processes.recovery(once=False)
            second = processes.recovery(once=False)
            starts = [json.loads(p.stdout.readline()) for p in (first, second)]
            assert all(line["operation"] == "recovery_start" for line in starts)
            shorten_lease(api, claimed, expired=True)
            wait_for_blocked(api, 1)
            waiters = wait_for_blocked(api, 2)
            assert len({row["pid"] for row in waiters}) == 2
            release(gate, key)
            logs = []
            for process, start in zip((first, second), starts):
                lines = [start]
                while True:
                    line = process.stdout.readline()
                    assert line, "Recovery exited before reporting settlement"
                    entry = json.loads(line)
                    lines.append(entry)
                    if entry.get("operation") == "recovery": break
                logs.append(lines)
                processes.kill(process)
        outcomes = [line for lines in logs for line in lines if line.get("operation") == "recovery"]
        assert sorted(line["outcome"] for line in outcomes) == ["expired", "noop"]
        before = row_for(api, db.partitions, claimed["partition_id"]), events(api)
        backoff = assert_backoff(api, claimed)
        restarted = processes.recover_once()
        assert restarted[-1]["candidates"] == 0
        assert (row_for(api, db.partitions, claimed["partition_id"]), events(api)) == before
        assert [e["type"] for e in events(api)][-2:] == ["ATTEMPT_EXPIRED", "PARTITION_READY"]
        assert [e["actor_type"] for e in events(api)[-2:]] == ["recovery", "recovery"]
        report("MULTI_RECOVERY", logs=logs, restart=restarted, waiters=waiters, backoff=backoff)
    finally: processes.close()


@pytest.mark.parametrize("operation", ["failure", "expiry"])
def test_settlement_event_abort_rolls_back_every_disposition(api, operation):
    new_job(api)
    owner = new_owner(api)
    claimed = fresh_claim(api, owner, 1)
    if operation == "expiry": shorten_lease(api, claimed, expired=True)
    before = row_for(api, db.attempts, claimed["attempt_id"]), row_for(api, db.partitions, claimed["partition_id"]), events(api)
    with api.admin_engine.begin() as c:
        c.exec_driver_sql("ALTER TABLE events ADD CONSTRAINT reject_m3_event CHECK (type NOT IN ('PARTITION_READY'))")
    try:
        if operation == "failure":
            response = fail_http(api, claimed, owner)
            assert response.status_code == 503 and response.json()["error"]["outcome"] == "not_committed"
        else:
            result = run_batch(api.engine)
            assert len(result) == 1 and result[0]["outcome"] == "unknown"
        assert (row_for(api, db.attempts, claimed["attempt_id"]), row_for(api, db.partitions, claimed["partition_id"]), events(api)) == before
    finally:
        with api.admin_engine.begin() as c: c.exec_driver_sql("ALTER TABLE events DROP CONSTRAINT reject_m3_event")
    if operation == "failure": assert fail_http(api, claimed, owner).status_code == 200
    else: assert run_batch(api.engine)[0]["outcome"] == "expired"
    assert_backoff(api, claimed)
    report("SETTLEMENT_ABORT", operation=operation, unchanged_before_retry=True, final_status=row_for(api, db.attempts, claimed["attempt_id"])["status"])
