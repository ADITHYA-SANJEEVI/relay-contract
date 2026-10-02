"""Localhost test runner for real worker barriers and lost response boundaries."""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from relay.worker.process import run

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert urlsplit(config["url"]).hostname == "127.0.0.1"
bootstrap = os.environ.pop("RELAY_WORKER_BOOTSTRAP_TOKEN")
claim_calls = completion_calls = 0


def wait_release(path):
    deadline = time.monotonic() + 90
    while not Path(path).exists():
        if time.monotonic() >= deadline: raise RuntimeError("test_barrier_deadline")
        time.sleep(0.01)


def claim_transport(client, session, headers, key):
    global claim_calls
    claim_calls += 1
    response = client.post(f"/v1/workers/{session}/claim", headers=headers | {"Idempotency-Key": key}, json={})
    assert response.status_code in (200, 201)
    marker = dict(worker_pid=os.getpid(), key=key, claim=response.json(), call=claim_calls)
    path = Path(config["claim_marker"])
    if claim_calls > 1:
        first = json.loads(path.read_text(encoding="utf-8"))
        assert key == first["key"]
        marker["original"] = first["claim"]
    path.write_text(json.dumps(marker), encoding="utf-8")
    if config.get("pause_after_claim"):
        wait_release(config["claim_release"])
    if config.get("lose_claim_response") and claim_calls == 1:
        raise httpx.ReadError("test_response_discard")
    return response


def before_publication(claimed, body, verified):
    if config.get("pause_before_publication"):
        # Called after production maintenance.stop(), before any HTTP publication
        # and therefore before publication row locks. No renewal runs at this gate.
        Path(config["publication_marker"]).write_text(json.dumps(dict(worker_pid=os.getpid(), claim=claimed,
            body=body, artifact=verified, renewals_stopped=True)), encoding="utf-8")
        wait_release(config["publication_release"])


def complete_transport(client, headers, claimed, body):
    global completion_calls
    completion_calls += 1
    response = client.post(f"/v1/attempts/{claimed['attempt_id']}/complete", headers=headers, json=body)
    path = Path(config["completion_marker"])
    marker = dict(body=body, status=response.status_code, response=response.json(), call=completion_calls)
    if completion_calls > 1:
        first = json.loads(path.read_text(encoding="utf-8"))
        assert body == first["body"]
        marker["original"] = first
    if config.get("repeat_rejection"):
        assert response.status_code == 409
        repeated = client.post(f"/v1/attempts/{claimed['attempt_id']}/complete", headers=headers, json=body)
        assert repeated.status_code == 409 and repeated.json() == response.json()
        marker["repeat"] = repeated.json()
    path.write_text(json.dumps(marker), encoding="utf-8")
    if config.get("lose_complete_response") and completion_calls == 1:
        assert response.status_code == 201
        # The success was committed, but is never delivered to the production run.
        # Cross the real nominal deadline; terminal metadata is never edited.
        deadline = datetime.fromisoformat(client.get(f"/v1/attempts/{claimed['attempt_id']}", headers=headers).json()["lease_expires_at"])
        bound = time.monotonic() + 35
        while True:
            view = client.get(f"/v1/attempts/{claimed['attempt_id']}", headers=headers).json()
            if datetime.fromisoformat(view["db_time"]) >= deadline:
                marker["crossed_db_time"] = view["db_time"]
                path.write_text(json.dumps(marker), encoding="utf-8")
                break
            if time.monotonic() >= bound: raise RuntimeError("test_deadline_bound")
            time.sleep(0.025)
        if config.get("unknown_503"):
            # Transport-boundary uncertainty injection, not a fabricated DB abort.
            return httpx.Response(503, json={"error": {"code": "database_unavailable", "outcome": "unknown"}})
        raise httpx.ReadError("test_response_discard")
    return response


try:
    child = (lambda task: [sys.executable, str(ROOT / "tests/faults/crash_child.py"), str(task), sys.argv[1]]) if config.get("mid_execution") else None
    result = run(config["url"], bootstrap, complete=True, _claim_transport=claim_transport,
                 _child_command=child, _before_publication=before_publication, _complete_transport=complete_transport)
    print(json.dumps(result, sort_keys=True))
except Exception as error:
    code = str(error) if isinstance(error, RuntimeError) else "test_worker_error"
    print(json.dumps({"phase": "WORKER_ERROR", "error_code": code, "error_type": type(error).__name__}))
    raise SystemExit(1)
