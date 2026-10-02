import hashlib
import json
from pathlib import Path
from uuid import UUID

import pyarrow as pa
import pytest
import sqlalchemy as sa

from relay.db import schema as db
from relay.workloads.reference import OUTPUT_SCHEMA, read_parquet
from tests.concurrency.test_m2 import cross_deadline, heartbeat, renew
from tests.concurrency.test_supervisor import child_alive, wait_path
from tests.integration.conftest import claim
from tests.integration.test_m1b import output_bytes, reserve_output, row_for
from tests.publication.test_m1c import complete, events, run_worker, shorten_lease
from tests.unit.oracle import serial_oracle
from .helpers import (Processes, advance_eligibility, assert_backoff, attempt_history, fail_http,
    fresh_claim, new_job, new_owner, report, target_results, verify_output)


def assert_oracle(api, trace, rows):
    response = api.client.get(f"/v1/artifacts/{trace['artifact_id']}/content", headers=api.operator)
    assert response.status_code == 200, response.text
    assert response.headers["X-Object-Version"] == trace["object_version"]
    assert hashlib.sha256(response.content).hexdigest() == trace["sha256"]
    expected, counters = serial_oracle(rows)
    assert read_parquet(pa.BufferReader(response.content), OUTPUT_SCHEMA).to_pylist() == expected
    assert trace["counters"] == counters
    return dict(sha256=hashlib.sha256(response.content).hexdigest(), bytes=len(response.content), oracle_groups=len(expected))


@pytest.mark.parametrize("phase", ["after_claim", "mid_execution"])
def test_t02_real_os_worker_crash_expiry_recovery_and_new_worker(api, phase):
    job, rows = new_job(api, lease=6)
    processes = Processes(api)
    try:
        crashed, config = processes.worker(pause_after_claim=phase == "after_claim", mid_execution=phase == "mid_execution")
        marker = wait_path(Path(config["claim_marker"]), crashed)
        old = marker["claim"]
        assert old["generation"] == "1" and old["job_id"] == job
        child = None
        if phase == "mid_execution":
            child = wait_path(Path(config["mid_marker"]), crashed)
            assert not child["credential_environment_present"] and child_alive(child["child_pid"])
            assert child["processed_rows"] == 3
            assert Path(child["partial_path"]).read_bytes() == b"local-unfinished-output-with-zero-authority"
        processes.kill(crashed)
        crashed.communicate(timeout=5)
        assert not child_alive(marker["worker_pid"])
        if child: assert not child_alive(child["child_pid"])
        assert target_results(api, old["partition_id"]) == []
        with api.engine.connect() as c:
            assert c.scalar(sa.select(sa.func.count()).select_from(db.artifacts)) == 0
        attempt = row_for(api, db.attempts, old["attempt_id"])
        expired_at = cross_deadline(api, attempt["lease_expires_at"])
        recovery = processes.recover_once()
        backoff = assert_backoff(api, old)
        terminal_old = row_for(api, db.attempts, old["attempt_id"])
        assert terminal_old["status"] == "EXPIRED" and terminal_old["failure_code"] == "lease_expired"
        advance_eligibility(api, old)
        result = run_worker(api)
        assert result["generation"] == "2" and result["worker_session_id"] != old["worker_session_id"]
        assert result["worker_pid"] != marker["worker_pid"] and result["attempt_id"] != old["attempt_id"]
        assert row_for(api, db.attempts, old["attempt_id"]) == terminal_old
        assert len(target_results(api, old["partition_id"])) == 1
        assert_oracle(api, result, rows)
        assert [a["status"] for a in attempt_history(api, old["partition_id"])] == ["EXPIRED", "SUCCEEDED"]
        report("T02", phase=phase, actual_crashed_pid=marker["worker_pid"], child_pid=child["child_pid"] if child else None,
            old_claim=old, expired_at=expired_at, recovery=recovery, backoff=backoff, new_worker=result,
            partial_output_authority=False, old_attempt=terminal_old)
    finally: processes.close()


def test_t03_real_expire_reassign_all_old_operations_have_zero_authority(api):
    new_job(api)
    old_owner = new_owner(api)
    old = fresh_claim(api, old_owner, 1)
    body, artifact = verify_output(api, old, old_owner, [])
    shorten_lease(api, old, expired=True)
    assert fail_http(api, old, old_owner).json()["error"]["code"] == "lease_expired"
    processes = Processes(api)
    try:
        recovery = processes.recover_once()
        backoff = assert_backoff(api, old)
        immutable_old = row_for(api, db.attempts, old["attempt_id"])
        advance_eligibility(api, old)
        new = fresh_claim(api, new_owner(api), 2)
        assert new["worker_session_id"] != old["worker_session_id"] and new["attempt_id"] != old["attempt_id"]
        latest_before = row_for(api, db.attempts, new["attempt_id"]), row_for(api, db.partitions, new["partition_id"])
        assert heartbeat(api, old_owner, "10").status_code == 200
        assert renew(api, old, old_owner, "10").status_code == 409
        assert fail_http(api, old, old_owner).status_code == 409
        assert reserve_output(api, old, old_owner, output_bytes([]))[0].status_code == 409
        rejected = complete(api, old, old_owner, body)
        assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "stale_generation"
        assert row_for(api, db.attempts, old["attempt_id"]) == immutable_old
        assert (row_for(api, db.attempts, new["attempt_id"]), row_for(api, db.partitions, new["partition_id"])) == latest_before
        assert target_results(api, new["partition_id"]) == []
        assert row_for(api, db.artifacts, artifact["id"])["status"] == "VERIFIED"
        report("T03", old=immutable_old, current=new, recovery=recovery, backoff=backoff,
            stale_publication_code=rejected.json()["error"]["code"], latest_generation=2)
    finally: processes.close()


def test_t04_exact_ordinal17_generations_1_through_5_real_stale_worker(api):
    job, rows = new_job(api, maximum=5, lease=6, partitions=18)
    historical_owner = new_owner(api)
    # Frozen TEST_PLAN's ordinal 17 has a real contiguous manifest. Complete
    # preceding work normally; every acceptance/count below is scoped to target.
    for ordinal in range(17):
        healthy = fresh_claim(api, historical_owner, 1)
        assert healthy["ordinal"] == ordinal
        healthy_body, _ = verify_output(api, healthy, historical_owner, rows[ordinal * 12:(ordinal + 1) * 12])
        assert complete(api, healthy, historical_owner, healthy_body).status_code == 201
    processes = Processes(api)
    trace = []
    try:
        for generation in range(1, 4):
            old = fresh_claim(api, historical_owner, generation)
            assert old["ordinal"] == 17
            shorten_lease(api, old, expired=True)
            recovery = processes.recover_once()
            assert target_results(api, old["partition_id"]) == []
            trace.append(dict(claim=old, recovery=recovery, backoff=advance_eligibility(api, old)))
        a, config = processes.worker(pause_before_publication=True, repeat_rejection=True)
        paused = wait_path(Path(config["publication_marker"]), a)
        generation4 = paused["claim"]
        assert generation4["generation"] == "4" and generation4["ordinal"] == 17 and paused["renewals_stopped"]
        artifact_a = row_for(api, db.artifacts, paused["artifact"]["id"])
        assert artifact_a["status"] == "VERIFIED" and target_results(api, generation4["partition_id"]) == []
        before_expiry = row_for(api, db.attempts, generation4["attempt_id"])
        expired_at = cross_deadline(api, before_expiry["lease_expires_at"])
        # The stopped supervisor never acknowledges another renewal during pause.
        assert row_for(api, db.attempts, generation4["attempt_id"])["last_renew_seq"] == before_expiry["last_renew_seq"]
        recovery4 = processes.recover_once()
        backoff4 = assert_backoff(api, generation4)
        assert target_results(api, generation4["partition_id"]) == []
        assert row_for(api, db.artifacts, str(artifact_a["id"])) == artifact_a
        expired4 = row_for(api, db.attempts, generation4["attempt_id"])
        assert expired4["status"] == "EXPIRED"
        advance_eligibility(api, generation4)
        b = run_worker(api)
        assert b["generation"] == "5" and b["partition_id"] == generation4["partition_id"]
        assert b["worker_session_id"] != generation4["worker_session_id"] and b["worker_pid"] != paused["worker_pid"]
        artifact_b = row_for(api, db.artifacts, b["artifact_id"])
        assert artifact_b["status"] == "VERIFIED" and artifact_b["object_key"] != artifact_a["object_key"]
        assert "/attempt-4/" in artifact_a["object_key"] and "/attempt-5/" in artifact_b["object_key"]
        assert artifact_b["object_version"] != artifact_a["object_version"] and artifact_b["id"] != artifact_a["id"]
        accepted_before = target_results(api, b["partition_id"])
        assert len(accepted_before) == 1 and accepted_before[0]["attempt_id"] == UUID(b["attempt_id"])
        assert accepted_before[0]["artifact_id"] == artifact_b["id"] and accepted_before[0]["generation"] == 5
        immutable5 = row_for(api, db.attempts, b["attempt_id"]), row_for(api, db.partitions, b["partition_id"])
        assert all(row["status"] == "SUCCEEDED" for row in immutable5)
        content = assert_oracle(api, b, rows[204:216])
        Path(config["publication_release"]).touch()
        stdout, stderr = a.communicate(timeout=15)
        assert a.returncode == 1, stdout + stderr
        assert json.loads(stdout)["error_code"] == "stale_generation"
        rejection = json.loads(Path(config["completion_marker"]).read_text(encoding="utf-8"))
        assert rejection["status"] == 409 and rejection["response"] == rejection["repeat"]
        assert rejection["body"] == paused["body"]
        assert target_results(api, b["partition_id"]) == accepted_before
        assert row_for(api, db.artifacts, str(artifact_a["id"])) == artifact_a
        assert row_for(api, db.artifacts, str(artifact_b["id"])) == artifact_b
        assert row_for(api, db.attempts, generation4["attempt_id"]) == expired4
        assert (row_for(api, db.attempts, b["attempt_id"]), row_for(api, db.partitions, b["partition_id"])) == immutable5
        target_events = [event for event in events(api) if event["partition_id"] == UUID(b["partition_id"])]
        assert [e["type"] for e in target_events].count("ATTEMPT_CLAIMED") == 5
        assert [e["type"] for e in target_events].count("ATTEMPT_EXPIRED") == 4
        assert [e["type"] for e in target_events].count("PARTITION_READY") == 4
        assert [e["type"] for e in target_events].count("RESULT_ACCEPTED") == 1
        assert [e["type"] for e in target_events].count("PUBLICATION_REJECTED") == 1
        assert [e["type"] for e in events(api)].count("JOB_SUCCEEDED") == 1
        history = attempt_history(api, b["partition_id"])
        assert [a["generation"] for a in history] == [1, 2, 3, 4, 5]
        assert [a["status"] for a in history] == ["EXPIRED"] * 4 + ["SUCCEEDED"]
        all_events = events(api)
        assert [e["seq"] for e in all_events] == list(range(1, len(all_events) + 1))
        report("T04", job_id=job, ordinal=17, partition=immutable5[1], prior_cycles=trace,
            paused_worker_pid=paused["worker_pid"], renewals_stopped=True, generation4_expired_at=expired_at,
            generation4_recovery=recovery4, generation4_backoff=backoff4, attempts=history,
            artifact_a=artifact_a, artifact_b=artifact_b, accepted=accepted_before, rejection=rejection,
            worker_b=b, exact_content=content, target_events=target_events, total_job_results=18)
    finally: processes.close()


@pytest.mark.parametrize("uncertainty", ["transport_loss", "unknown_503"])
def test_t11_worker_reconciles_same_completion_after_commit_and_nominal_expiry(api, uncertainty):
    _, rows = new_job(api, lease=6)
    processes = Processes(api)
    try:
        worker, config = processes.worker(lose_claim_response=True, lose_complete_response=True,
                                         unknown_503=uncertainty == "unknown_503")
        stdout, stderr = worker.communicate(timeout=30)
        assert worker.returncode == 0, stdout + stderr
        result = json.loads(stdout)
        claim_marker = json.loads(Path(config["claim_marker"]).read_text(encoding="utf-8"))
        assert claim_marker["call"] == 2 and claim_marker["claim"] == claim_marker["original"] | {"replay": True}
        marker = json.loads(Path(config["completion_marker"]).read_text(encoding="utf-8"))
        assert marker["status"] == 200 and marker["call"] == 2 and marker["response"]["replay"]
        assert marker["body"] == marker["original"]["body"]
        assert marker["response"]["accepted_result"] == marker["original"]["response"]["accepted_result"]
        assert marker["original"]["status"] == 201 and marker["original"]["crossed_db_time"]
        assert result["phase"] == "ACCEPTED" and result["generation"] == "1"
        assert result["reconciliations"] == [{"operation": "complete", "status": "SUCCEEDED", "accepted_result": result["accepted_result"]}]
        assert len(target_results(api, result["partition_id"])) == 1
        assert len(attempt_history(api, result["partition_id"])) == 1
        assert [e["type"] for e in events(api)].count("RESULT_ACCEPTED") == 1
        with api.engine.connect() as c:
            receipts = [dict(row) for row in c.execute(sa.select(db.request_receipts).where(db.request_receipts.c.operation == "claim")).mappings()]
            assert len(receipts) == 1 and receipts[0]["key"] == claim_marker["key"]
        assert_oracle(api, result, rows)
        report("T11", uncertainty=uncertainty, worker=result, claim_key=claim_marker["key"], completion=marker)
    finally: processes.close()
