"""Test-only localhost runner; production CLI has no fault-control flags."""
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from relay.worker.process import run

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert urlsplit(config["url"]).hostname == "127.0.0.1"
bootstrap = os.environ.pop("RELAY_WORKER_BOOTSTRAP_TOKEN")


def lost_response(client, session, headers, key):
    path = f"/v1/workers/{session}/claim"
    first = client.post(path, headers=headers | {"Idempotency-Key": key}, json={})
    assert first.status_code == 201
    marker = {"session_id": session, "claim_key": key, "claim": first.json()}
    Path(config["claim_marker"]).write_text(json.dumps(marker), encoding="utf-8")
    if config.get("expire_replay"):
        while not Path(config["claim_release"]).exists(): time.sleep(0.01)
    # Deterministically discard the committed response, return only the retry.
    replay = client.post(path, headers=headers | {"Idempotency-Key": key}, json={})
    marker.update(replay=replay.json(), current_before_execution=client.get(
        f"/v1/attempts/{marker['claim']['attempt_id']}", headers=headers).json())
    Path(config["claim_marker"]).write_text(json.dumps(marker), encoding="utf-8")
    return replay


try:
    result = run(config["url"], bootstrap, complete=True,
        _child_command=lambda task: [sys.executable, str(ROOT / "tests/concurrency/controlled_child.py"), str(task), sys.argv[1]],
        _claim_transport=lost_response if config.get("lose_claim_response") else None)
    print(json.dumps(result, sort_keys=True))
except RuntimeError as error:
    print(json.dumps({"phase": "WORKER_ERROR", "error_code": str(error)}))
    raise SystemExit(1)
