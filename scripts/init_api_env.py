"""Add distinct local API tokens to ignored .env; never display values."""

import secrets
from pathlib import Path

from dotenv import dotenv_values

path = Path(__file__).resolve().parents[1] / ".env"
if not path.exists(): raise SystemExit("Run scripts/init_env.py first")
values = dotenv_values(path)
with path.open("a", encoding="utf-8", newline="\n") as file:
    for key in ("RELAY_OPERATOR_TOKEN", "RELAY_WORKER_BOOTSTRAP_TOKEN"):
        if not values.get(key) or values[key].startswith("REPLACE_"):
            file.write(f"\n{key}={secrets.token_hex(32)}\n")
print("Local API tokens configured in ignored .env; existing tokens preserved.")
