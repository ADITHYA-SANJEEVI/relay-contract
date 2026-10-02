import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pyarrow as pa

from relay.workloads.reference import INPUT_SCHEMA, OUTPUT_SCHEMA_HASH, WORKLOAD_DIGEST, read_parquet
from .maintenance import Maintenance

ROOT = Path(__file__).resolve().parents[3]


def compute_child(client, headers, claim, maintenance, command_factory=None):
    cache = (ROOT / ".cache" / "workers").resolve()
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="task_", dir=cache) as temporary:
        directory = Path(temporary).resolve()
        assert directory.parent == cache
        paths = []
        for index, part in enumerate(claim["inputs"]):
            maintenance.check()
            if not part["download_url"].startswith(f"/v1/attempts/{claim['attempt_id']}/inputs/"):
                raise RuntimeError("invalid_slice_url")
            response = client.get(part["download_url"], headers=headers)
            if response.status_code != 200: require(response, (200,))
            table = read_parquet(pa.BufferReader(response.content), INPUT_SCHEMA)
            if table.num_rows != int(part["row_count"]): raise RuntimeError("slice_row_count")
            path = directory / f"input_{index}.parquet"
            path.write_bytes(response.content); paths.append(str(path))
        output_path = directory / "output.parquet"
        config_path = directory / "task.json"
        config_path.write_text(json.dumps({"inputs": paths, "output": str(output_path)}), encoding="utf-8")
        command = (command_factory(config_path) if command_factory else
                   [sys.executable, str(ROOT / "scripts/run_workload.py"), str(config_path)])
        essentials = {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}
        child_env = {k: v for k, v in os.environ.items() if k.upper() in essentials}
        maintenance.check()
        # The trusted child emits only one bounded counters/identity JSON object.
        child = subprocess.Popen(command, cwd=ROOT, env=child_env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            while child.poll() is None:
                maintenance.check(); time.sleep(0.025)
            maintenance.check()
            if child.returncode: raise RuntimeError("computation_failed")
        finally:
            if child.poll() is None:
                if os.name == "nt":
                    # The Windows venv launcher may own a second Python process.
                    # Target only our launched child and its descendants.
                    system_root = next(v for k, v in os.environ.items() if k.upper() == "SYSTEMROOT")
                    try:
                        subprocess.run([str(Path(system_root) / "System32" / "taskkill.exe"),
                            "/PID", str(child.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=2,
                            creationflags=subprocess.CREATE_NO_WINDOW)
                    except (OSError, subprocess.TimeoutExpired):
                        child.terminate()
                else:
                    child.terminate()
                try: child.wait(timeout=2)
                except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=2)
            # Drain to EOF as well as waiting for the launcher: descendants must
            # close inherited handles before temporary task files are removed.
            stdout, _ = child.communicate(timeout=2)
        result = json.loads(stdout)
        if result["credential_environment_present"]: raise RuntimeError("child_credential_environment")
        return output_path.read_bytes(), result


def require(response, status):
    if response.status_code not in status:
        try: code = response.json()["error"]["code"]
        except (ValueError, KeyError): code = "unexpected_response"
        raise RuntimeError(code)
    return response.json()


def run(base_url, bootstrap, *, polls=1, display_name="relay-worker", complete=False,
        _child_command=None, _claim_transport=None):
    # A fresh boot identity; never reuse a prior process's session automatically.
    session, secret = str(uuid4()), secrets.token_hex(32)
    started = time.monotonic()
    with httpx.Client(base_url=base_url, timeout=15, trust_env=False) as client:
        require(client.post("/v1/workers/register", headers={"Authorization": "Bearer " + bootstrap}, json={
            "session_id": session, "session_secret": secret, "display_name": display_name,
            "deployment_workload_digest": WORKLOAD_DIGEST}), (201,))
        headers = {"Authorization": "Bearer " + secret, "X-Worker-Session": session}
        claim = None
        for index in range(polls):
            claim_key = str(uuid4())
            if _claim_transport:
                response = _claim_transport(client, session, headers, claim_key)
            else:
                response = client.post(f"/v1/workers/{session}/claim", headers=headers | {"Idempotency-Key": claim_key}, json={})
            if response.status_code == 204:
                if index + 1 < polls: time.sleep(min(0.25 * 2 ** index, 2))
                continue
            claim = require(response, (201, 200)); break
        if claim is None:
            return {"phase": "NO_WORK", "worker_session_id": session, "worker_pid": os.getpid()}
        # A receipt is historical. Inspect current ownership before starting any child.
        observed_at = time.monotonic()
        current = require(client.get(f"/v1/attempts/{claim['attempt_id']}", headers=headers), (200,))
        now = datetime.fromisoformat(current["db_time"])
        if (current["status"] != "ACTIVE" or current["current_generation"] != claim["generation"]
            or current["generation"] != claim["generation"] or current["partition_id"] != claim["partition_id"]
            or current["job_status"] != "RUNNING" or current["partition_status"] != "RUNNING"
            or now >= datetime.fromisoformat(current["lease_expires_at"])
            or now >= datetime.fromisoformat(current["hard_deadline_at"])):
            raise RuntimeError("claim_replay_not_live" if claim["replay"] else "claim_not_live")
        maintenance = Maintenance(base_url, headers, claim, current, observed_at)
        maintenance.start()
        try:
            return finish(client, headers, claim, maintenance, started, session, complete, _child_command)
        finally:
            maintenance.stop()


def finish(client, headers, claim, maintenance, started, session, complete, child_command):
    data, child = compute_child(client, headers, claim, maintenance, child_command)
    counters = child["counters"]
    maintenance.check()
    digest = hashlib.sha256(data).hexdigest()
    artifact = require(client.post(f"/v1/attempts/{claim['attempt_id']}/artifact", headers=headers, json={
        "job_id": claim["job_id"], "partition_id": claim["partition_id"], "generation": claim["generation"],
        "sha256": digest, "size_bytes": str(len(data)), "schema_hash": OUTPUT_SCHEMA_HASH}), (201, 200))
    if artifact["upload_url"] != f"/v1/artifacts/{artifact['id']}/content": raise RuntimeError("invalid_upload_url")
    maintenance.check()
    verified = require(client.put(artifact["upload_url"], headers=headers | {
        "Content-Type": "application/vnd.apache.parquet"}, content=data), (200,))
    if (verified["status"] != "VERIFIED" or verified["sha256"] != digest
        or verified["size_bytes"] != str(len(data)) or verified["schema_hash"] != OUTPUT_SCHEMA_HASH):
        raise RuntimeError("verification_identity_mismatch")
    accepted = None
    if complete:
        # Avoid renewal racing the successful ACTIVE->SUCCEEDED transition.
        maintenance.stop()
        maintenance.check()
        publication = require(client.post(f"/v1/attempts/{claim['attempt_id']}/complete", headers=headers, json={
            "request_id": str(uuid4()), "job_id": claim["job_id"], "partition_id": claim["partition_id"],
            "generation": claim["generation"], "artifact_id": verified["id"],
            "artifact_uri": verified["artifact_uri"], "sha256": digest}), (201, 200))
        accepted = publication["accepted_result"]
        if (accepted["artifact_id"] != verified["id"] or accepted["sha256"] != digest
            or accepted["attempt_id"] != claim["attempt_id"] or accepted["generation"] != claim["generation"]
            or accepted["object_version"] != verified["object_version"]
            or accepted["partition_id"] != claim["partition_id"]):
            raise RuntimeError("acceptance_identity_mismatch")
    return dict(phase="ACCEPTED" if complete else "VERIFIED_UNACCEPTED", worker_pid=os.getpid(), worker_session_id=session,
        child_pid=child["child_pid"], child_credential_environment_present=child["credential_environment_present"],
        renewals=maintenance.trace, original_lease_expires_at=claim["lease_expires_at"],
        job_id=claim["job_id"], partition_id=claim["partition_id"], attempt_id=claim["attempt_id"],
        generation=claim["generation"], artifact_id=verified["id"], object_version=verified["object_version"],
        sha256=digest, size_bytes=str(len(data)), counters=counters,
        **({"accepted_result": accepted, "job_status": publication["job_status"]} if complete else {}),
        elapsed_seconds=round(time.monotonic() - started, 3))
