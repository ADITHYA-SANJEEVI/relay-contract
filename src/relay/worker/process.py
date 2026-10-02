import hashlib
import io
import json
import os
import secrets
import time
from datetime import datetime
from uuid import uuid4

import httpx
import pyarrow as pa

from relay.workloads.reference import (INPUT_SCHEMA, OUTPUT_SCHEMA_HASH, WORKLOAD_DIGEST,
                                       execute, read_parquet, write_parquet)


def require(response, status):
    if response.status_code not in status:
        try: code = response.json()["error"]["code"]
        except (ValueError, KeyError): code = "unexpected_response"
        raise RuntimeError(code)
    return response.json()


def run(base_url, bootstrap, *, polls=1, display_name="relay-worker", complete=False):
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
            response = client.post(f"/v1/workers/{session}/claim", headers=headers | {"Idempotency-Key": str(uuid4())}, json={})
            if response.status_code == 204:
                if index + 1 < polls: time.sleep(min(0.25 * 2 ** index, 2))
                continue
            claim = require(response, (201, 200)); break
        if claim is None:
            return {"phase": "NO_WORK", "worker_session_id": session, "worker_pid": os.getpid()}
        if claim["replay"]:
            # M1B has no renewal. Query the original ownership; do not infer a new lease.
            current = require(client.get(f"/v1/attempts/{claim['attempt_id']}", headers=headers), (200,))
            now = datetime.fromisoformat(current["db_time"])
            if (current["status"] != "ACTIVE" or current["current_generation"] != claim["generation"]
                or current["job_status"] != "RUNNING" or current["partition_status"] != "RUNNING"
                or now >= datetime.fromisoformat(current["lease_expires_at"])
                or now >= datetime.fromisoformat(current["hard_deadline_at"])):
                raise RuntimeError("claim_replay_not_live")
        tables = []
        for part in claim["inputs"]:
            if not part["download_url"].startswith(f"/v1/attempts/{claim['attempt_id']}/inputs/"):
                raise RuntimeError("invalid_slice_url")
            response = client.get(part["download_url"], headers=headers)
            if response.status_code != 200: require(response, (200,))
            table = read_parquet(pa.BufferReader(response.content), INPUT_SCHEMA)
            if table.num_rows != int(part["row_count"]): raise RuntimeError("slice_row_count")
            tables.append(table)
        output, counters = execute(tables)
        content = io.BytesIO()
        write_parquet(output, content)
        data = content.getvalue()
        digest = hashlib.sha256(data).hexdigest()
        artifact = require(client.post(f"/v1/attempts/{claim['attempt_id']}/artifact", headers=headers, json={
            "job_id": claim["job_id"], "partition_id": claim["partition_id"], "generation": claim["generation"],
            "sha256": digest, "size_bytes": str(len(data)), "schema_hash": OUTPUT_SCHEMA_HASH}), (201, 200))
        if artifact["upload_url"] != f"/v1/artifacts/{artifact['id']}/content": raise RuntimeError("invalid_upload_url")
        verified = require(client.put(artifact["upload_url"], headers=headers | {
            "Content-Type": "application/vnd.apache.parquet"}, content=data), (200,))
        if (verified["status"] != "VERIFIED" or verified["sha256"] != digest
            or verified["size_bytes"] != str(len(data)) or verified["schema_hash"] != OUTPUT_SCHEMA_HASH):
            raise RuntimeError("verification_identity_mismatch")
        accepted = None
        if complete:
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
            job_id=claim["job_id"], partition_id=claim["partition_id"], attempt_id=claim["attempt_id"],
            generation=claim["generation"], artifact_id=verified["id"], object_version=verified["object_version"],
            sha256=digest, size_bytes=str(len(data)), counters=counters,
            **({"accepted_result": accepted, "job_status": publication["job_status"]} if complete else {}),
            elapsed_seconds=round(time.monotonic() - started, 3))
