"""Worker CLI receives only an API bootstrap credential, never reads .env."""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

# Also strip ambient infrastructure credentials from a manually launched worker.
for key in list(os.environ):
    if key.startswith(("POSTGRES_", "S3_", "AWS_")) or key == "RELAY_OPERATOR_TOKEN":
        del os.environ[key]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from relay.worker.process import run

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:8000")
parser.add_argument("--polls", type=int, default=1)
parser.add_argument("--complete", action="store_true", help="Publish the verified artifact through the fenced complete endpoint")
args = parser.parse_args()
url = urlsplit(args.base_url)
if url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost") or url.username or url.password:
    raise SystemExit("Relay worker requires the trusted localhost API")
bootstrap = os.environ.pop("RELAY_WORKER_BOOTSTRAP_TOKEN", "")
if not bootstrap: raise SystemExit("RELAY_WORKER_BOOTSTRAP_TOKEN is required")
try:
    if not 1 <= args.polls <= 100: raise ValueError("invalid_poll_bound")
    print(json.dumps(run(args.base_url, bootstrap, polls=args.polls, complete=args.complete), sort_keys=True))
except Exception as error:
    # No raw request, token, data or traceback in worker output.
    safe_code = str(error) if isinstance(error, (RuntimeError, ValueError)) and re.fullmatch(r"[a-z_]{1,64}", str(error)) else "worker_error"
    print(json.dumps({"phase": "WORKER_ERROR", "error_type": type(error).__name__, "error_code": safe_code}), file=sys.stderr)
    raise SystemExit(1)
