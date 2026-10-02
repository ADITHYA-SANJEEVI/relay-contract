"""Test-only local child barrier and CPU duration. No network or credentials."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from relay.worker.child import compute

config = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
marker = Path(config["ready"])
marker.write_text(json.dumps({"child_pid": os.getpid(), "credential_environment_present": any(
    k.upper().startswith(("POSTGRES_", "S3_", "AWS_", "RELAY_")) for k in os.environ)}), encoding="utf-8")
while not Path(config["release"]).exists():
    time.sleep(0.01)
deadline = time.monotonic() + config.get("duration_seconds", 0)
value = b"relay-test-cpu"
while time.monotonic() < deadline:
    value = hashlib.sha256(value).digest()
result = compute(sys.argv[1])
Path(config["finished"]).write_text("completed", encoding="utf-8")
print(json.dumps(result, sort_keys=True))
