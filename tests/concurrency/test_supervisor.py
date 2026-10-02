import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import UUID, uuid4

import pyarrow as pa
import sqlalchemy as sa

from relay.db import schema as db
from relay.workloads.reference import OUTPUT_SCHEMA, read_parquet
from tests.integration.conftest import ROOT, claim, submission, submit_job, verified_input
from tests.integration.test_m1b import row_for
from tests.publication.test_m1c import accepted_rows, events, shorten_lease
from tests.unit.oracle import serial_oracle
from tests.unit.test_reference import fixture_rows
from .test_m2 import heartbeat, renew, report, worker_row


def worker_env(api):
    return {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP")} | {
        "RELAY_WORKER_BOOTSTRAP_TOKEN": api.settings["RELAY_WORKER_BOOTSTRAP_TOKEN"]}


def wait_path(path, process, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size:
            try: return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError: pass
        assert process.poll() is None, "Test worker exited before barrier"
        time.sleep(0.025)
    raise AssertionError("Test worker barrier deadline exceeded")


def child_alive(pid):
    if os.name != "nt":
        try: os.kill(pid, 0); return True
        except ProcessLookupError: return False
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle: return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally: kernel.CloseHandle(handle)


class Workers:
    def __init__(self, api):
        self.api, self.processes = api, []
        cache = (ROOT / ".cache" / "m2-workers").resolve(); cache.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="run_", dir=cache)
        self.directory = Path(self.temporary.name).resolve()
        assert self.directory.parent == cache

    def start(self, index=0, **changes):
        config = dict(url=self.api.url, ready=str(self.directory / f"ready_{index}.json"),
            release=str(self.directory / f"release_{index}"), finished=str(self.directory / f"finished_{index}"),
            duration_seconds=7, claim_marker=str(self.directory / f"claim_{index}.json"),
            claim_release=str(self.directory / f"claim_release_{index}")) | changes
        path = self.directory / f"worker_{index}.json"; path.write_text(json.dumps(config), encoding="utf-8")
        process = subprocess.Popen([sys.executable, str(ROOT / "tests/concurrency/controlled_supervisor.py"), str(path)],
            cwd=ROOT, env=worker_env(self.api), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.processes.append((process, config)); return process, config

    def close(self):
        for process, config in self.processes:
            if process.poll() is None: process.terminate(); process.wait(timeout=5)
            marker = Path(config["ready"])
            if marker.exists():
                pid = json.loads(marker.read_text())["child_pid"]
                if child_alive(pid):
                    if os.name == "nt":
                        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                        kernel.OpenProcess.restype = ctypes.c_void_p
                        kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                        handle = kernel.OpenProcess(1, False, pid)
                        if handle: kernel.TerminateProcess(handle, 1); kernel.CloseHandle(handle)
                    else: os.kill(pid, 15)
        assert self.directory.name.startswith("run_") and self.directory.parent.name == "m2-workers"
        self.temporary.cleanup()


def job(api, partitions=1, lease=6):
    rows = fixture_rows(12 * partitions)
    identity, _, _ = verified_input(api, rows)
    submitted = submit_job(api, submission(identity, len(rows), split=[(i * 12, 12) for i in range(partitions)]) | {
        "policy": {"lease_seconds": lease, "max_attempt_seconds": 60}})
    assert submitted.status_code == 201
    return submitted.json()["id"], rows


def test_real_supervisor_child_runs_beyond_initial_lease(api):
    job_id, rows = job(api)
    workers = Workers(api)
    try:
        process, config = workers.start()
        ready = wait_path(Path(config["ready"]), process)
        assert not ready["credential_environment_present"] and ready["child_pid"] != process.pid
        Path(config["release"]).touch()
        stdout, stderr = process.communicate(timeout=25)
        assert process.returncode == 0, stdout + stderr
        result = json.loads(stdout)
        assert result["phase"] == "ACCEPTED" and result["worker_pid"] not in (os.getpid(), api.pid, ready["child_pid"])
        assert len(result["renewals"]) >= 3 and not result["child_credential_environment_present"]
        assert result["accepted_result"]["accepted_at"] > result["original_lease_expires_at"]
        content = api.client.get(f"/v1/artifacts/{result['artifact_id']}/content", headers=api.operator)
        assert read_parquet(pa.BufferReader(content.content), OUTPUT_SCHEMA).to_pylist() == serial_oracle(rows)[0]
        assert len(accepted_rows(api)) == 1 and row_for(api, db.jobs, job_id)["status"] == "SUCCEEDED"
        assert not child_alive(ready["child_pid"]) and Path(config["finished"]).exists()
        report("SUPERVISOR_LONG", api_pid=api.pid, result=result, ready=ready)
    finally: workers.close()


def test_supervisor_rejected_renew_terminates_child_no_artifact(api):
    job(api, lease=6)
    workers = Workers(api)
    try:
        process, config = workers.start(duration_seconds=30)
        ready = wait_path(Path(config["ready"]), process)
        with api.engine.connect() as c:
            attempt = dict(c.execute(sa.select(db.attempts)).mappings().one())
            partition = dict(c.execute(sa.select(db.partitions)).mappings().one())
        claimed = dict(attempt_id=str(attempt["id"]), partition_id=str(partition["id"]), job_id=str(partition["job_id"]))
        shorten_lease(api, claimed, expired=True)
        stdout, stderr = process.communicate(timeout=10)
        assert stdout, stderr
        assert process.returncode == 1 and json.loads(stdout)["error_code"] == "renewal_authority_lost"
        assert not child_alive(ready["child_pid"]) and not Path(config["finished"]).exists()
        logs = [json.loads(line) for line in api.log_path.read_text(encoding="utf-8").splitlines() if line.startswith("{")]
        assert any(entry.get("operation") == "renew" and entry.get("error_code") == "lease_expired" for entry in logs)
        assert accepted_rows(api) == []
        with api.engine.connect() as c:
            assert c.scalar(sa.select(sa.func.count()).select_from(db.artifacts)) == 0
        assert not any(e["type"] in ("ARTIFACT_RESERVED", "RESULT_ACCEPTED") for e in events(api))
        assert row_for(api, db.attempts, claimed["attempt_id"])["status"] == "ACTIVE"
        report("SUPERVISOR_LOSS", supervisor_pid=process.pid, child_pid=ready["child_pid"], result=json.loads(stdout), artifact_count=0, accepted_count=0)
    finally: workers.close()


def test_t18_lost_response_live_replay_supervisor(api):
    job(api)
    workers = Workers(api)
    try:
        process, config = workers.start(lose_claim_response=True)
        marker = wait_path(Path(config["claim_marker"]), process)
        ready = wait_path(Path(config["ready"]), process)
        marker = json.loads(Path(config["claim_marker"]).read_text(encoding="utf-8"))
        before = marker["current_before_execution"]
        assert before["last_renew_seq"] == "0"
        assert before["lease_expires_at"] == marker["claim"]["lease_expires_at"]
        assert before["claimed_at"] == marker["claim"]["claimed_at"]
        assert marker["replay"] == marker["claim"] | {"replay": True}
        Path(config["release"]).touch()
        stdout, stderr = process.communicate(timeout=25)
        assert process.returncode == 0, stdout + stderr
        result = json.loads(stdout)
        assert result["attempt_id"] == marker["claim"]["attempt_id"] and result["generation"] == "1"
        with api.engine.connect() as c:
            receipts = [dict(r) for r in c.execute(sa.select(db.request_receipts).where(db.request_receipts.c.operation == "claim")).mappings()]
            assert len(receipts) == 1
            assert receipts[0]["response"] == marker["claim"] and receipts[0]["key"] == marker["claim_key"]
            assert c.scalar(sa.select(sa.func.count()).select_from(db.attempts)) == 1
        assert [e["type"] for e in events(api)].count("ATTEMPT_CLAIMED") == 1
        report("T18_LIVE", lost_claim=marker, result=result, child_pid=ready["child_pid"])
    finally: workers.close()


def test_t18_expired_replay_supervisor_never_starts_child(api):
    job(api)
    workers = Workers(api)
    try:
        process, config = workers.start(lose_claim_response=True, expire_replay=True)
        marker = wait_path(Path(config["claim_marker"]), process)
        expired = shorten_lease(api, marker["claim"], expired=True)
        Path(config["claim_release"]).touch()
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 1 and json.loads(stdout)["error_code"] == "claim_replay_not_live"
        marker = json.loads(Path(config["claim_marker"]).read_text(encoding="utf-8"))
        assert marker["replay"] == marker["claim"] | {"replay": True}
        assert not Path(config["ready"]).exists()
        attempt = row_for(api, db.attempts, marker["claim"]["attempt_id"])
        assert attempt["lease_expires_at"] == expired and attempt["generation"] == 1 and attempt["last_renew_seq"] == 0
        with api.engine.connect() as c:
            assert c.scalar(sa.select(sa.func.count()).select_from(db.request_receipts).where(db.request_receipts.c.operation == "claim")) == 1
            assert c.scalar(sa.select(sa.func.count()).select_from(db.artifacts)) == 0
        assert accepted_rows(api) == [] and [e["type"] for e in events(api)].count("ATTEMPT_CLAIMED") == 1
        logs = [json.loads(line) for line in api.log_path.read_text(encoding="utf-8").splitlines() if line.startswith("{")]
        assert any(entry.get("operation") == "claim" and entry.get("outcome") == "replay" for entry in logs)
        report("T18_EXPIRED", receipt_claim=marker, current_lease=expired, result=json.loads(stdout), child_started=False)
    finally: workers.close()


def test_t20_two_process_boots_and_session_isolation(api):
    job(api, lease=30)
    workers = Workers(api)
    try:
        bindings = []
        for index in range(2):
            config = dict(url=api.url, binding=str(workers.directory / f"binding_{index}.json"))
            path = workers.directory / f"probe_{index}.json"; path.write_text(json.dumps(config), encoding="utf-8")
            process = subprocess.Popen([sys.executable, str(ROOT / "tests/concurrency/session_probe.py"), str(path)], cwd=ROOT,
                env=worker_env(api), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, stdout + stderr
            bindings.append(json.loads(Path(config["binding"]).read_text()))
        a, b = bindings
        assert a["pid"] != b["pid"] and a["session"] != b["session"]
        distinct_credentials = a["secret"] != b["secret"]
        assert distinct_credentials, "Independent boots reused credentials (redacted)"
        assert a["claim"] is not None and b["claim"] is None
        ah = {"Authorization": "Bearer " + a["secret"], "X-Worker-Session": a["session"]}
        bh = {"Authorization": "Bearer " + b["secret"], "X-Worker-Session": b["session"]}
        before = worker_row(api, ah)
        impostor = bh | {"X-Worker-Session": a["session"]}
        assert heartbeat(api, impostor, "8").status_code == 401
        assert renew(api, a["claim"], bh).status_code == 403
        publication = api.client.post(f"/v1/attempts/{a['claim']['attempt_id']}/complete", headers=bh, json={
            **{k: a["claim"][k] for k in ("job_id", "partition_id", "generation")}, "request_id": str(uuid4()),
            "artifact_id": str(uuid4()), "artifact_uri": "s3://unknown/test?versionId=x", "sha256": "a" * 64})
        assert publication.status_code == 403
        for sequence in ("7", "6"):
            assert not heartbeat(api, ah, sequence).json()["applied"]
        assert heartbeat(api, bh, "8").status_code == 200
        assert worker_row(api, ah) == before and before["state"] == "REGISTERED"
        assert row_for(api, db.attempts, a["claim"]["attempt_id"])["lease_expires_at"].isoformat() == a["claim"]["lease_expires_at"]
        assert claim(api, bh).status_code == 204
        job(api, lease=30)  # A separate READY partition, no reassignment of A.
        ready_claim = claim(api, bh)
        assert ready_claim.status_code == 201 and ready_claim.json()["partition_id"] != a["claim"]["partition_id"]
        assert row_for(api, db.partitions, a["claim"]["partition_id"])["generation"] == 1
        report("T20", boots=[{k: x[k] for k in ("pid", "session")} for x in bindings], old_session=before,
               old_attempt=a["claim"]["attempt_id"], new_attempt=ready_claim.json()["attempt_id"], wrong_owner_status=403)
    finally: workers.close()


def test_three_concurrent_worker_processes_renew_and_publish_oracle(api):
    job_id, rows = job(api, partitions=3)
    workers = Workers(api)
    try:
        running = [workers.start(index=i) for i in range(3)]
        ready = [wait_path(Path(config["ready"]), process) for process, config in running]
        with api.engine.connect() as c:
            attempts = [dict(r) for r in c.execute(sa.select(db.attempts)).mappings()]
            assert len(attempts) == 3 and all(a["status"] == "ACTIVE" for a in attempts)
            assert len({a["worker_session_id"] for a in attempts}) == len({a["partition_id"] for a in attempts}) == 3
        for process, config in running: Path(config["release"]).touch()
        results = []
        for process, config in running:
            stdout, stderr = process.communicate(timeout=25)
            assert process.returncode == 0, stdout + stderr
            result = json.loads(stdout); results.append(result)
            assert result["phase"] == "ACCEPTED" and len(result["renewals"]) >= 3
            assert result["accepted_result"]["accepted_at"] > result["original_lease_expires_at"]
        assert len({r["worker_pid"] for r in results}) == len({r["child_pid"] for r in results}) == 3
        assert len(accepted_rows(api)) == 3 and row_for(api, db.jobs, job_id)["status"] == "SUCCEEDED"
        parts = api.client.get(f"/v1/jobs/{job_id}/partitions", headers=api.operator).json()["items"]
        for result in results:
            ordinal = next(p["ordinal"] for p in parts if p["id"] == result["partition_id"])
            content = api.client.get(f"/v1/artifacts/{result['artifact_id']}/content", headers=api.operator)
            assert content.status_code == 200
            assert read_parquet(pa.BufferReader(content.content), OUTPUT_SCHEMA).to_pylist() == serial_oracle(rows[ordinal * 12:(ordinal + 1) * 12])[0]
            assert not result["child_credential_environment_present"]
        assert [e["type"] for e in events(api)].count("RESULT_ACCEPTED") == 3
        report("MULTI_WORKER", api_pid=api.pid, initial_active=3, results=results, accepted_count=3)
    finally: workers.close()
