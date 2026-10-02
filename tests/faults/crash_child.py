"""Actual CPU computation and a local partial output before an OS crash."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from relay.workloads.reference import INPUT_SCHEMA, execute, read_parquet, write_parquet

config = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
task = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
partial = Path(task["output"])


class ControlledTable:
    def __init__(self, table):
        self.table, self.schema = table, table.schema

    def to_pylist(self):
        for index, row in enumerate(self.table.to_pylist()):
            yield row
            if index == 2:
                # Production execute has consumed/normalized the first three
                # assigned rows, and is still inside its aggregation loop.
                partial.write_bytes(b"local-unfinished-output-with-zero-authority")
                Path(config["mid_marker"]).write_text(json.dumps({"child_pid": os.getpid(), "processed_rows": 3,
                    "partial_path": str(partial), "credential_environment_present": any(
                    k.upper().startswith(("RELAY_", "POSTGRES_", "S3_", "AWS_")) for k in os.environ)}), encoding="utf-8")
                value, deadline = b"relay-mid-computation", time.monotonic() + 60
                while not Path(config["child_release"]).exists() and time.monotonic() < deadline:
                    value = hashlib.sha256(value).digest()


output, counters = execute([ControlledTable(read_parquet(path, INPUT_SCHEMA)) for path in task["inputs"]])
write_parquet(output, task["output"])
print(json.dumps({"child_pid": os.getpid(), "counters": counters, "credential_environment_present": False}))
