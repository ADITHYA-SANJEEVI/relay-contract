"""Independent recovery process. Runtime DB authority only; no store/worker token."""
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from relay.db.connection import database_url, make_engine
from relay.recovery.service import run_batch
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--once", action="store_true", help="Run one discovery batch and exit")
    args = parser.parse_args()
    # No ambient credential or administrative fallback. Only these file fields
    # are retained; neither API config nor the artifact gateway is imported.
    values = dotenv_values(args.env_file, interpolate=False)
    settings = {k: values[k] for k in ("POSTGRES_RUNTIME_PASSWORD", "POSTGRES_PORT", "POSTGRES_DATABASE") if values.get(k)}
    del values
    engine = make_engine(database_url(settings))
    try:
        with engine.connect() as c:
            if c.scalar(text("SELECT current_user")) != "relay_runtime":
                raise ValueError("Recovery requires runtime database authority")
        print(json.dumps({"operation": "recovery_start", "pid": os.getpid(), "poll_seconds": 1, "batch": 100}), flush=True)
        while True:
            try:
                results = run_batch(engine)
                print(json.dumps({"operation": "recovery_poll", "candidates": len(results)}), flush=True)
            except SQLAlchemyError:
                print(json.dumps({"operation": "recovery", "outcome": "unknown", "reason": "database_unavailable"}), flush=True)
            if args.once:
                break
            time.sleep(1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(json.dumps({"operation": "recovery", "outcome": "error", "error_type": type(error).__name__}), file=sys.stderr)
        raise SystemExit(1)
