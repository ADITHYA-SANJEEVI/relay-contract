"""Private local subprocess entry point; accepts only local computation files."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from relay.worker.child import compute

try:
    print(json.dumps(compute(sys.argv[1]), sort_keys=True))
except Exception:
    print(json.dumps({"error_code": "computation_failed"}), file=sys.stderr)
    raise SystemExit(1)
