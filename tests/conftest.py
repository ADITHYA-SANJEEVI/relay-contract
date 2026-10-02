"""M0 fixtures require healthy real Compose services and explicit credentials."""

import json
import subprocess
from pathlib import Path

import boto3
import psycopg
import pytest
from botocore.config import Config
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


class LocalSettings(dict):
    """Pytest includes fixture arguments on failure; never render credentials."""
    def __repr__(self):
        return "LocalSettings(<redacted>)"

    __str__ = __repr__


@pytest.fixture(scope="session")
def settings():
    values = LocalSettings(dotenv_values(ROOT / ".env"))
    for name in (
        "POSTGRES_PASSWORD",
        "POSTGRES_PORT",
        "S3_PORT",
        "S3_BUCKET",
        "S3_ADMIN_ACCESS_KEY",
        "S3_ADMIN_SECRET_KEY",
        "S3_RUNTIME_ACCESS_KEY",
        "S3_RUNTIME_SECRET_KEY",
    ):
        if not values.get(name) or values[name].startswith("REPLACE_"):
            pytest.fail(f"Missing real local configuration: {name}")
    if values["S3_ADMIN_ACCESS_KEY"] == values["S3_RUNTIME_ACCESS_KEY"]:
        pytest.fail("Admin and runtime identities must be distinct")
    if values["S3_ADMIN_SECRET_KEY"] == values["S3_RUNTIME_SECRET_KEY"]:
        pytest.fail("Admin and runtime secrets must be distinct")
    return values


def require_compose_service(service, expected_image):
    output = subprocess.check_output(
        ["docker", "compose", "ps", "--format", "json", service],
        cwd=ROOT,
        text=True,
        timeout=20,
    )
    rows = [json.loads(line) for line in output.splitlines() if line.strip()]
    assert len(rows) == 1, f"Expected one real Compose {service} service"
    row = rows[0]
    assert row["State"] == "running", row
    assert row["Health"] == "healthy", row
    assert row["Image"] == expected_image, row
    print(json.dumps({"service": service, "state": row["State"], "health": row["Health"], "image": row["Image"]}))


@pytest.fixture(scope="session")
def pg_connect(settings):
    require_compose_service(
        "postgres",
        "postgres:18.6-trixie@sha256:5a5a84b19854a9ffaa54082c166ff4ec27473a361e496e5ea167f298f2da9722",
    )

    def connect():
        return psycopg.connect(
            host="127.0.0.1",
            port=int(settings["POSTGRES_PORT"]),
            dbname="relay_m0",
            user="relay_m0",
            password=settings["POSTGRES_PASSWORD"],
            connect_timeout=5,
            autocommit=True,
            options="-c statement_timeout=5000 -c lock_timeout=2000 -c idle_in_transaction_session_timeout=5000",
        )

    return connect


@pytest.fixture(scope="session")
def storage(settings):
    require_compose_service("minio", "relay-m0-minio:RELEASE.2025-10-15T17-29-55Z")

    def client(privilege):
        # Explicit credentials: no ambient AWS chain and no admin fallback.
        return boto3.client(
            "s3",
            endpoint_url=f"http://127.0.0.1:{int(settings['S3_PORT'])}",
            region_name="us-east-1",
            aws_access_key_id=settings[f"S3_{privilege}_ACCESS_KEY"],
            aws_secret_access_key=settings[f"S3_{privilege}_SECRET_KEY"],
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"total_max_attempts": 1},
                connect_timeout=5,
                read_timeout=10,
            ),
        )

    admin, runtime = client("ADMIN"), client("RUNTIME")
    yield admin, runtime, settings["S3_BUCKET"]
    admin.close()
    runtime.close()
