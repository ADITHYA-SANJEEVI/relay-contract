"""Generate local M0 credentials without displaying or overwriting them."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
values = {
    "POSTGRES_PASSWORD": secrets.token_hex(24),
    "POSTGRES_PORT": "54328",
    "S3_PORT": "9000",
    "S3_BUCKET": "relay-m0-contract",
    "S3_ADMIN_ACCESS_KEY": "admin" + secrets.token_hex(8),
    "S3_ADMIN_SECRET_KEY": secrets.token_hex(24),
    "S3_RUNTIME_ACCESS_KEY": "runtime" + secrets.token_hex(8),
    "S3_RUNTIME_SECRET_KEY": secrets.token_hex(24),
}
with (root / ".env").open("x", encoding="utf-8", newline="\n") as file:
    file.write("".join(f"{key}={value}\n" for key, value in values.items()))
print("Created ignored .env with distinct local credentials; values not displayed.")
