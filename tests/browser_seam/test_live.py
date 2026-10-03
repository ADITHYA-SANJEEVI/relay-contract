"""Real HTTP BFF -> API -> PostgreSQL/MinIO, no in-memory authority substitute."""

import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx

from relay.browser.session import COOKIE
from tests.integration.conftest import ROOT, register
from tests.integration.test_m1b import row_for
from tests.operator_visibility.test_visibility import durable_state
from tests.publication.test_m1c import complete, prepared
from relay.db import schema as db


@contextmanager
def local_directory(cache):
    temporary = tempfile.TemporaryDirectory(prefix="run_", dir=cache)
    path = Path(temporary.name).resolve()
    assert path.parent == cache.resolve() and path.name.startswith("run_")
    try:
        yield path
    finally:
        # OneDrive/Windows scanners may briefly hold a log after the child exits.
        deadline = time.monotonic() + 3
        while True:
            try:
                temporary.cleanup()
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)


@contextmanager
def seam(api, *, token=None, backend=None, origin=None):
    cache = ROOT / ".cache/browser-tests"
    cache.mkdir(parents=True, exist_ok=True)
    with local_directory(cache) as directory:
        temporary = Path(directory)
        env_file, pairing, logs = temporary / ".env", temporary / "pairing", temporary / "bff.log"
        secret = token or api.settings["RELAY_OPERATOR_TOKEN"]
        env_file.write_text("RELAY_OPERATOR_TOKEN=" + secret + "\n")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        browser_origin = origin or url
        process = None
        with logs.open("w", encoding="utf-8") as log:
            try:
                process = subprocess.Popen([sys.executable, str(ROOT / "scripts/serve_board.py"),
                    "--env-file", str(env_file), "--backend", backend or api.url.rstrip("/"), "--port", str(port),
                    "--origin", browser_origin,
                    "--pairing-file", str(pairing)], cwd=ROOT, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                with httpx.Client(base_url=url, trust_env=False, timeout=20,
                        headers={"Host": browser_origin.removeprefix("http://"), "Origin": browser_origin,
                                 "X-Relay-Board": "1", "Sec-Fetch-Site": "same-origin"}) as client:
                    deadline = time.monotonic() + 15
                    while True:
                        assert process.poll() is None, "BFF exited during startup (logs withheld for secret safety)"
                        try:
                            result = client.get("/board-connect")
                            if result.status_code == 200 and pairing.is_file(): break
                        except httpx.TransportError: pass
                        assert time.monotonic() < deadline, "BFF startup deadline exceeded"
                        time.sleep(0.05)
                    yield client, pairing.read_text(), logs
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
                assert temporary.resolve().parent == cache.resolve() and temporary.name.startswith("run_")


def bootstrap(client, code):
    response = client.post("/board-api/session", json={"pairing_code": code})
    assert response.status_code == 200
    return response


def read(client, path, **params):
    response = client.get("/board-api/operator/" + path, params=params)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["X-Request-Id"]
    assert response.json()["snapshot_scope"] == "request_repeatable_read"
    assert response.json()["as_of"]
    return response


def test_real_smoke_all_16_reads_authority_verification_secrets_no_mutation(api):
    claimed, owner, body = prepared(api)
    assert complete(api, claimed, owner, body).status_code == 201
    job, partition, attempt, artifact, worker = (claimed["job_id"], claimed["partition_id"],
        claimed["attempt_id"], body["artifact_id"], claimed["worker_session_id"])
    before = durable_state(api)
    with seam(api) as (client, code, logs):
        outputs = [client.get("/board-connect"), client.get("/board-connect.js"), client.get("/board")]
        assert all(response.status_code == 200 for response in outputs)
        assets = sorted((ROOT / "frontend/dist/assets").glob("*"))
        assert assets, "Build the frontend before the real compiled-asset smoke"
        for asset in assets:
            response = client.get("/board/assets/" + asset.name)
            assert response.status_code == 200
            assert response.headers["Cache-Control"] == "private, no-store"
            outputs.append(response)
        assert client.get("/board-api/operator/capabilities").status_code == 401
        outputs.append(bootstrap(client, code))
        paths = ("capabilities", "jobs", f"jobs/{job}", f"jobs/{job}/partitions",
            f"partitions/{partition}", f"partitions/{partition}/history", f"attempts/{attempt}",
            f"artifacts/{artifact}", f"artifacts/{artifact}/verification", f"jobs/{job}/result-metadata",
            f"jobs/{job}/events", "workers", f"workers/{worker}", f"workers/{worker}/attempts",
            f"workers/{worker}/events", f"jobs/{job}/definition")
        responses = {path: read(client, path) for path in paths}
        outputs.extend(responses.values())
        direct = api.client.get("/v1/operator/capabilities", headers=api.operator).json()
        bff = responses["capabilities"].json()
        direct_cap = {item["id"]: item for item in direct["capabilities"]}
        bff_cap = {item["id"]: item for item in bff["capabilities"]}
        assert direct_cap.pop("BV10_BROWSER_AUTH")["state"] == "DEFERRED"
        assert bff_cap.pop("BV10_BROWSER_AUTH")["state"] == "AVAILABLE"
        assert direct_cap == bff_cap and direct["database_revision"] == bff["database_revision"]
        assert responses["jobs"].json()["items"][0]["id"] == job
        assert responses[f"jobs/{job}"].json()["job"]["partition_count"] == "1"
        accepted = responses[f"partitions/{partition}"].json()["partition"]["accepted_authority"]
        assert accepted["status"] == "ACCEPTED" and accepted["result"]["artifact_id"] == artifact
        assert responses[f"jobs/{job}/result-metadata"].json()["items"][0]["authority"] == accepted
        assert responses[f"artifacts/{artifact}/verification"].json()["verification"]["state"] == "VERIFIED"
        # Filters and pagination are passed to the existing R1 implementation.
        events = read(client, f"jobs/{job}/events", direction="backward", limit=1).json()
        assert events["has_more"] and isinstance(events["next_cursor"], str)
        assert isinstance(events["frontier_seq"], str)
        assert read(client, f"jobs/{job}/definition").json()["scope"] == "complete_immutable_definition"
        for response in outputs:
            assert api.settings["RELAY_OPERATOR_TOKEN"] not in response.text
            assert api.settings["RELAY_OPERATOR_TOKEN"] not in str(dict(response.headers))
            assert code not in response.text
        assert api.settings["RELAY_OPERATOR_TOKEN"] not in logs.read_text()
        assert code not in logs.read_text()
        assert durable_state(api) == before
        # Remove only the test's pinned object version; observation must retain authority.
        row = row_for(api, db.artifacts, artifact)
        api.storage[0].delete_object(Bucket=row["bucket"], Key=row["object_key"], VersionId=row["object_version"])
        failure = read(client, f"artifacts/{artifact}/verification").json()
        assert failure["verification"]["state"] == "FAILED"
        assert failure["verification"]["code"] in ("storage_missing", "version_unavailable")
        assert failure["accepted_authority"] == accepted
        assert durable_state(api) == before
        print("BV10 real HTTP smoke: 16 R1 reads, authenticated catalogue/capabilities, pinned verification failure, no authority mutations")


def test_real_auth_worker_separation_errors_restart_and_offline(api):
    worker_secret = secrets.token_hex(32)
    registered, _, worker_headers = register(api, secret=worker_secret)
    assert registered.status_code == 201
    before = durable_state(api)
    with seam(api) as (client, code, logs):
        assert client.post("/board-api/session", json={"pairing_code": worker_secret}).status_code == 422
        assert client.get("/board-api/operator/jobs", headers=worker_headers).status_code == 401
        assert client.get("/board-api/operator/jobs", headers=api.operator).status_code == 401
        bootstrap(client, code)
        old_cookie = client.cookies.get(COOKIE)
        assert client.get("/board-api/operator/jobs", headers=worker_headers).status_code == 401
        missing = client.get(f"/board-api/operator/jobs/{uuid4()}")
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
        invalid = client.get("/board-api/operator/jobs?limit=0")
        assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "invalid_request"
        assert client.post("/board-api/operator/jobs", json={}).status_code == 404
        assert worker_secret not in logs.read_text() and code not in logs.read_text()
    with seam(api) as (client, new_code, logs):
        assert new_code != code
        assert client.get("/board-api/operator/jobs", headers={"Cookie": COOKIE + "=" + old_cookie}).status_code == 401
        assert client.post("/board-api/session", json={"pairing_code": code}).status_code == 401
        bootstrap(client, new_code)
        assert read(client, "jobs").json()["items"] == []
    with seam(api, token=secrets.token_urlsafe(32)) as (client, new_code, logs):
        bootstrap(client, new_code)
        rejected = client.get("/board-api/operator/jobs")
        assert rejected.status_code == 401 and rejected.json()["error"]["code"] == "unauthenticated"
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        backend = f"http://127.0.0.1:{unused.getsockname()[1]}"
        with seam(api, backend=backend) as (client, new_code, logs):
            bootstrap(client, new_code)
            offline = client.get("/board-api/operator/capabilities")
            assert offline.status_code == 503 and offline.json()["error"]["code"] == "browser_backend_unavailable"
            assert offline.headers["Cache-Control"] == "private, no-store"
    assert durable_state(api) == before


def test_real_vite_same_origin_proxy_and_server_file_denial(api):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    before = durable_state(api)
    # Load the real Vite config, overriding only occupied-risk ports/target for isolation.
    script = """import {createServer} from 'vite';
const target=process.argv[2];
const server=await createServer({server:{port:Number(process.argv[1]),strictPort:true,
proxy:{'/board-api':{target},'/board-connect':{target}}},clearScreen:false});
await server.listen();"""
    with seam(api, origin=origin) as (bff, code, bff_logs):
        with local_directory(ROOT / ".cache/browser-tests") as temporary:
            logs = temporary / "vite.log"
            process = None
            with logs.open("w", encoding="utf-8") as log:
                try:
                    process = subprocess.Popen(["node", "--input-type=module", "-e", script, str(port), str(bff.base_url).rstrip("/")],
                        cwd=ROOT / "frontend", stdout=log, stderr=log,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    with httpx.Client(base_url=origin, trust_env=False, timeout=20,
                            headers={"Origin": origin, "X-Relay-Board": "1", "Sec-Fetch-Site": "same-origin"}) as client:
                        deadline = time.monotonic() + 20
                        while True:
                            assert process.poll() is None, "Vite proxy exited"
                            try:
                                connect = client.get("/board-connect")
                                if connect.status_code == 200: break
                            except httpx.TransportError: pass
                            assert time.monotonic() < deadline, "Vite startup deadline exceeded"
                            time.sleep(0.05)
                        assert "frame-ancestors 'none'" in connect.headers["Content-Security-Policy"]
                        assert client.get("/board-api/operator/jobs").status_code == 401
                        bootstrap(client, code)
                        assert read(client, "capabilities").json()["capabilities"][9]["state"] == "AVAILABLE"
                        assert read(client, "jobs").json()["items"] == []
                        assert client.get("/board/").status_code == 200
                        # Default Vite filesystem protection must keep BFF env out of dev output.
                        env_path = (bff_logs.parent / ".env").as_posix()
                        denied = client.get("/board/@fs/" + env_path)
                        assert denied.status_code in (403, 404)
                        assert api.settings["RELAY_OPERATOR_TOKEN"] not in denied.text
                        assert api.settings["RELAY_OPERATOR_TOKEN"] not in logs.read_text()
                finally:
                    if process is not None and process.poll() is None:
                        process.terminate()
                        try: process.wait(timeout=10)
                        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
    assert durable_state(api) == before
