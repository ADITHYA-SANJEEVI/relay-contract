"""Local computation only. No session, HTTP, database or store authority."""

import json
import os
from pathlib import Path

from relay.workloads.reference import INPUT_SCHEMA, execute, read_parquet, write_parquet


def compute(config_path):
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    tables = [read_parquet(path, INPUT_SCHEMA) for path in config["inputs"]]
    output, counters = execute(tables)
    write_parquet(output, config["output"])
    return dict(counters=counters, child_pid=os.getpid(), credential_environment_present=any(
        k.upper().startswith(("POSTGRES_", "S3_", "AWS_", "RELAY_")) for k in os.environ))
