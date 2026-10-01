import io
import os
import secrets
import socket
import subprocess
import sys
import time
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pyarrow as pa
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from relay.db.connection import database_url, make_engine
from relay.workloads.reference import INPUT_SCHEMA, INPUT_SCHEMA_HASH, WORKLOAD, write_parquet
from tests.unit.test_reference import fixture_rows

ROOT = Path(__file__).resolve().parents[2]


class Harness(SimpleNamespace):
    def __repr__(self):
        return f"M1BHarness(database={self.database}, api_pid={self.pid})"


@pytest.fixture
def api(pg_connect, settings, storage):
    cache = (ROOT / ".cache" / "m1b-tests").resolve()
    cache.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="run_", dir=cache)
    tmp_path = Path(temporary.name).resolve()
    assert tmp_path.parent == cache
    name = "relay_m1b_test_" + uuid4().hex
    values = {k: settings[k] for k in ("POSTGRES_RUNTIME_PASSWORD", "POSTGRES_PORT", "S3_PORT", "S3_BUCKET",
                                      "S3_RUNTIME_ACCESS_KEY", "S3_RUNTIME_SECRET_KEY")}
    values.update(POSTGRES_DATABASE=name, RELAY_OPERATOR_TOKEN=secrets.token_hex(32),
                  RELAY_WORKER_BOOTSTRAP_TOKEN=secrets.token_hex(32))
    with pg_connect() as c:
        c.execute(sql.SQL("CREATE DATABASE {} OWNER relay_m0").format(sql.Identifier(name)))
        c.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO relay_runtime").format(sql.Identifier(name)))
    engine = make_engine(database_url(settings, migration=True).set(database=name))
    runtime_engine = make_engine(database_url(values))
    process = None
    log_path = tmp_path / "api.log"
    try:
        with engine.begin() as c:
            config = Config(str(ROOT / "alembic.ini")); config.attributes["connection"] = c
            command.upgrade(config, "head")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        env_file = tmp_path / ".env"
        env_file.write_text("\n".join(f"{key}={value}" for key,value in values.items()) + "\n")
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, str(ROOT / "scripts/serve.py"), "--env-file", str(env_file),
                                        "--port", str(port)], cwd=ROOT, stdout=log, stderr=log,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=15, trust_env=False) as client:
                deadline = time.monotonic() + 15
                while True:
                    if process.poll() is not None: pytest.fail("API startup failed: " + log_path.read_text())
                    try:
                        response = client.get("/health/ready")
                        if response.status_code == 200: break
                    except httpx.TransportError: pass
                    if time.monotonic() >= deadline: pytest.fail("API readiness deadline exceeded")
                    time.sleep(0.05)
                yield Harness(client=client, settings=values, engine=runtime_engine, admin_engine=engine,
                    operator={"Authorization": "Bearer " + values["RELAY_OPERATOR_TOKEN"]},
                    bootstrap={"Authorization": "Bearer " + values["RELAY_WORKER_BOOTSTRAP_TOKEN"]},
                    pid=process.pid, log_path=log_path, url=str(client.base_url), storage=storage,
                    database=name)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        engine.dispose(); runtime_engine.dispose()
        with pg_connect() as c:
            assert name.startswith("relay_m1b_test_") and len(name) == 47
            c.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
        # Cleanup is restricted to this exact newly allocated workspace child.
        assert tmp_path.resolve().parent == cache and tmp_path.name.startswith("run_")
        temporary.cleanup()


def parquet_bytes(rows):
    buffer = io.BytesIO()
    write_parquet(pa.Table.from_pylist(rows, schema=INPUT_SCHEMA), buffer)
    return buffer.getvalue()


def reserve_input(api, data, *, key=None, **changes):
    import hashlib
    body = dict(sha256=hashlib.sha256(data).hexdigest(), size_bytes=str(len(data)),
                media_type="application/vnd.apache.parquet", schema_hash=INPUT_SCHEMA_HASH) | changes
    response = api.client.post("/v1/inputs", headers=api.operator | {"Idempotency-Key": key or str(uuid4())}, json=body)
    return response, body


def verified_input(api, rows=None):
    rows = fixture_rows(12) if rows is None else rows
    data = parquet_bytes(rows)
    response, body = reserve_input(api, data)
    assert response.status_code == 201, response.text
    identity = response.json()["id"]
    uploaded = api.client.put(f"/v1/inputs/{identity}/content", headers=api.operator, content=data)
    assert uploaded.status_code == 200, uploaded.text
    return identity, data, rows


def submission(input_id, count, *, split=None):
    partitions = [{"ordinal": 0, "slices": [{"input_ordinal": 0, "first_row": "0", "row_count": str(count)}]}]
    if split is not None:
        partitions = [dict(ordinal=i, slices=[dict(input_ordinal=0, first_row=str(start), row_count=str(size))])
                      for i,(start,size) in enumerate(split)]
    return dict(workload=WORKLOAD, inputs=[dict(input_ordinal=0, artifact_id=input_id)], partitions=partitions)


def submit_job(api, body, key=None):
    return api.client.post("/v1/jobs", headers=api.operator | {"Idempotency-Key": key or str(uuid4())}, json=body)


def register(api, *, session=None, secret=None, **changes):
    from relay.workloads.reference import WORKLOAD_DIGEST
    session, secret = session or str(uuid4()), secret or secrets.token_hex(32)
    body = dict(session_id=session, session_secret=secret, display_name="test-worker",
                deployment_workload_digest=WORKLOAD_DIGEST) | changes
    response = api.client.post("/v1/workers/register", headers=api.bootstrap, json=body)
    return response, body, {"Authorization": "Bearer " + secret, "X-Worker-Session": session}


def claim(api, headers, key=None):
    return api.client.post(f"/v1/workers/{headers['X-Worker-Session']}/claim",
                          headers=headers | {"Idempotency-Key": key or str(uuid4())}, json={})
