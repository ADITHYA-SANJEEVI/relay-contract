"""Real-service M3 controls, confined to disposable databases/cache children."""
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import sqlalchemy as sa

from relay.control.common import wire
from relay.db import schema as db
from tests.integration.conftest import ROOT, claim, register, submission, submit_job, verified_input
from tests.integration.test_m1b import output_bytes, reserve_output, row_for
from tests.publication.test_m1c import complete, events
from tests.concurrency.test_supervisor import child_alive, wait_path, worker_env


def report(name, **values):
    print("M3 " + name, json.dumps(wire(values), sort_keys=True))


def new_job(api, *, maximum=5, lease=30, partitions=1):
    from tests.unit.test_reference import fixture_rows
    rows = fixture_rows(12 * partitions)
    identity, _, _ = verified_input(api, rows)
    body = submission(identity, len(rows), split=[(i * 12, 12) for i in range(partitions)])
    response = submit_job(api, body | {"policy": {
        "max_attempts": maximum, "lease_seconds": lease, "max_attempt_seconds": 60}})
    assert response.status_code == 201, response.text
    return response.json()["id"], rows


def new_owner(api):
    response, _, headers = register(api)
    assert response.status_code == 201
    return headers


def fresh_claim(api, headers, generation):
    response = claim(api, headers)
    assert response.status_code == 201, response.text
    assert response.json()["generation"] == str(generation)
    return response.json()


def failure_body(claimed, code="worker_crash", detail=None):
    return {k: claimed[k] for k in ("job_id", "partition_id", "generation")} | {
        "code": code, "detail": {} if detail is None else detail}


def fail_http(api, claimed, headers, body=None):
    return api.client.post(f"/v1/attempts/{claimed['attempt_id']}/fail", headers=headers,
                           json=body or failure_body(claimed))


def independent_post(api, path, headers, body):
    with httpx.Client(base_url=api.url, trust_env=False, timeout=10) as client:
        return client.post(path, headers=headers, json=body)


def verify_output(api, claimed, headers, rows):
    data = output_bytes(rows)
    reservation, _ = reserve_output(api, claimed, headers, data)
    assert reservation.status_code == 201, reservation.text
    response = api.client.put(reservation.json()["upload_url"], headers=headers, content=data)
    assert response.status_code == 200, response.text
    verified = response.json()
    body = {k: claimed[k] for k in ("job_id", "partition_id", "generation")} | {
        "request_id": str(uuid4()), "artifact_id": verified["id"], "artifact_uri": verified["artifact_uri"],
        "sha256": verified["sha256"]}
    return body, verified


def attempt_history(api, partition):
    with api.engine.connect() as c:
        return [dict(row) for row in c.execute(sa.select(db.attempts).where(
            db.attempts.c.partition_id == UUID(partition)).order_by(db.attempts.c.generation)).mappings()]


def target_results(api, partition):
    with api.engine.connect() as c:
        return [dict(row) for row in c.execute(sa.select(db.accepted_results).where(
            db.accepted_results.c.partition_id == UUID(partition))).mappings()]


def assert_backoff(api, claimed):
    attempt = row_for(api, db.attempts, claimed["attempt_id"])
    partition = row_for(api, db.partitions, claimed["partition_id"])
    seconds = min(2 ** (int(claimed["generation"]) - 1), 30)
    assert attempt["status"] in ("FAILED", "EXPIRED") and partition["status"] == "READY"
    assert partition["generation"] == partition["latest_generation_fk"] == int(claimed["generation"])
    assert partition["eligible_at"] == attempt["finished_at"] + timedelta(seconds=seconds)
    assert partition["last_error_code"] == attempt["failure_code"] and partition["finished_at"] is None
    return dict(generation=attempt["generation"], finished_at=attempt["finished_at"],
                eligible_at=partition["eligible_at"], backoff_seconds=seconds)


def advance_eligibility(api, claimed):
    # Assert the production outcome BEFORE the only test-only retry bypass.
    trace = assert_backoff(api, claimed)
    with api.engine.begin() as c:
        c.execute(sa.select(db.jobs).where(db.jobs.c.id == UUID(claimed["job_id"])).with_for_update())
        c.execute(sa.select(db.partitions).where(db.partitions.c.id == UUID(claimed["partition_id"])).with_for_update())
        c.execute(sa.select(db.attempts).where(db.attempts.c.id == UUID(claimed["attempt_id"])).with_for_update())
        c.execute(db.partitions.update().where(db.partitions.c.id == UUID(claimed["partition_id"]))
                  .values(eligible_at=sa.func.clock_timestamp()))
    return trace


class Processes:
    def __init__(self, api):
        self.api, self.processes = api, []
        cache = (ROOT / ".cache" / "m3-processes").resolve()
        cache.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="run_", dir=cache)
        self.directory = Path(self.temporary.name).resolve()
        assert self.directory.parent == cache
        # Independent recovery receives ONLY its runtime DB credential.
        self.recovery_env = self.directory / "recovery.env"
        self.recovery_env.write_text("\n".join(f"{k}={api.settings[k]}" for k in (
            "POSTGRES_RUNTIME_PASSWORD", "POSTGRES_PORT", "POSTGRES_DATABASE")), encoding="utf-8")

    def worker(self, index=0, **changes):
        config = dict(url=self.api.url, claim_marker=str(self.directory / f"claim_{index}.json"),
            claim_release=str(self.directory / f"claim_release_{index}"),
            publication_marker=str(self.directory / f"publication_{index}.json"),
            publication_release=str(self.directory / f"publication_release_{index}"),
            completion_marker=str(self.directory / f"completion_{index}.json"),
            mid_marker=str(self.directory / f"mid_{index}.json"), child_release=str(self.directory / f"child_release_{index}")) | changes
        path = self.directory / f"worker_{index}.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        process = self.start([sys.executable, str(ROOT / "tests/faults/controlled_worker.py"), str(path)], worker_env(self.api))
        return process, config

    def start(self, command, env):
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.processes.append(process)
        return process

    def recovery(self, *, once=True):
        env = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP")}
        assert not any(k.upper().startswith(("POSTGRES_", "S3_", "RELAY_", "AWS_")) for k in env)
        return self.start([sys.executable, str(ROOT / "scripts/run_recovery.py"), "--env-file", str(self.recovery_env)]
                          + (["--once"] if once else []), env)

    def recover_once(self):
        process = self.recovery()
        stdout, stderr = process.communicate(timeout=12)
        assert process.returncode == 0, stdout + stderr
        lines = [json.loads(line) for line in stdout.splitlines()]
        assert lines[0]["operation"] == "recovery_start" and lines[0]["pid"] not in (os.getpid(), self.api.pid)
        assert lines[0]["batch"] == 100 and lines[0]["poll_seconds"] == 1
        return lines

    def kill(self, process):
        # Only a Popen identity allocated by this harness; include its venv tree.
        assert process in self.processes
        if process.poll() is None:
            if os.name == "nt":
                root = next(v for k, v in os.environ.items() if k.upper() == "SYSTEMROOT")
                result = subprocess.run([str(Path(root) / "System32/taskkill.exe"), "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
                assert result.returncode == 0, "Owned process tree termination failed"
            else:
                process.kill()
            process.wait(timeout=5)

    def close(self):
        for process in self.processes:
            self.kill(process)
            process.communicate(timeout=5)
        assert self.directory.parent == (ROOT / ".cache/m3-processes").resolve() and self.directory.name.startswith("run_")
        self.temporary.cleanup()


@contextmanager
def attempt_barrier(api, predicate):
    # Test-only BEFORE UPDATE trigger, held AFTER all canonical locks/time.
    key = int(uuid4().hex[:7], 16)
    with api.admin_engine.begin() as c:
        c.exec_driver_sql(f"CREATE FUNCTION m3_barrier() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
            f"IF {predicate} THEN PERFORM pg_advisory_xact_lock({key}); END IF; RETURN NEW; END; $$")
        c.exec_driver_sql("CREATE TRIGGER m3_barrier BEFORE UPDATE ON attempts FOR EACH ROW EXECUTE FUNCTION m3_barrier()")
    gate = api.admin_engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    gate.execute(sa.text("SELECT pg_advisory_lock(:key)"), {"key": key})
    try:
        yield gate, key
    finally:
        gate.execute(sa.text("SELECT pg_advisory_unlock(:key)"), {"key": key})
        gate.close()
        with api.admin_engine.begin() as c:
            c.exec_driver_sql("DROP TRIGGER m3_barrier ON attempts")
            c.exec_driver_sql("DROP FUNCTION m3_barrier()")


def release(gate, key):
    gate.execute(sa.text("SELECT pg_advisory_unlock(:key)"), {"key": key})
