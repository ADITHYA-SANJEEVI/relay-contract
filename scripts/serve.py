"""Run one localhost M1B API process; PostgreSQL and MinIO remain Compose-backed."""

import argparse
import logging
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from relay.api.app import app_from_file

parser = argparse.ArgumentParser()
parser.add_argument("--env-file", default=str(ROOT / ".env"))
parser.add_argument("--port", type=int, default=8000)
args = parser.parse_args()
logging.basicConfig(level=logging.INFO, format="%(message)s")
app = app_from_file(args.env_file)
uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")
