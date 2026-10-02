"""Independent test process boot: private binding file, no secret in stdout."""
import json
import os
import secrets
import sys
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from relay.workloads.reference import WORKLOAD_DIGEST

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
session, secret = str(uuid4()), secrets.token_hex(32)
with httpx.Client(base_url=config["url"], trust_env=False) as client:
    response = client.post("/v1/workers/register", headers={"Authorization": "Bearer " + os.environ.pop("RELAY_WORKER_BOOTSTRAP_TOKEN")},
        json=dict(session_id=session, session_secret=secret, display_name="restart-probe", deployment_workload_digest=WORKLOAD_DIGEST))
    assert response.status_code == 201
    headers = {"Authorization": "Bearer " + secret, "X-Worker-Session": session}
    assert client.post(f"/v1/workers/{session}/heartbeat", headers=headers, json={"sequence": "7"}).status_code == 200
    response = client.post(f"/v1/workers/{session}/claim", headers=headers | {"Idempotency-Key": str(uuid4())}, json={})
    assert response.status_code in (201, 204)
    Path(config["binding"]).write_text(json.dumps(dict(session=session, secret=secret, pid=os.getpid(),
        claim=response.json() if response.status_code == 201 else None)), encoding="utf-8")
    print(json.dumps(dict(session=session, pid=os.getpid(), claim_status=response.status_code)))
# Intentional process exit without STOP or attempt settlement.
