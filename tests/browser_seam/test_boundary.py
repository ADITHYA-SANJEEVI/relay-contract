import asyncio
import json
import secrets
from pathlib import Path

import httpx
import pytest

from relay.browser.app import Config, MAX_RESPONSE, create_app
from relay.browser.session import COOKIE, PAIR_SECONDS, SESSION_SECONDS

ORIGIN = "http://127.0.0.1:8001"
HEADERS = {"X-Relay-Board": "1", "Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}


def scenario(tmp_path, run, upstream=None, operator_token=None):
    """Exercise real ASGI/session routing with a controlled upstream failure boundary."""
    token, code = operator_token or secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    clock = [0.0]
    config = Config("http://127.0.0.1:8000", ORIGIN, tmp_path, token)
    transport = httpx.MockTransport(upstream or (lambda request: httpx.Response(503)))
    app = create_app(config, code, clock=lambda: clock[0], upstream_transport=transport)

    async def main():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN,
                                         headers=HEADERS) as client:
                await run(client, code, token, clock, app)
    asyncio.run(main())


async def pair(client, code):
    response = await client.post("/board-api/session", json={"pairing_code": code})
    assert response.status_code == 200
    return response


def test_session_cookie_expiry_logout_replay_and_hashes(tmp_path):
    async def run(client, code, token, clock, app):
        assert (await client.get("/board-api/session")).status_code == 401
        assert (await client.get("/board-api/operator/jobs")).status_code == 401
        assert (await client.post("/board-api/session", json={"pairing_code": secrets.token_urlsafe(32)})).status_code == 401
        result = await pair(client, code)
        cookie = client.cookies.get(COOKIE)
        assert cookie != code and cookie != token
        assert token not in result.text and code not in result.text and cookie not in result.text
        header = result.headers["set-cookie"]
        for value in ("HttpOnly", "SameSite=strict", "Path=/board-api", "Max-Age=1800"):
            assert value in header
        assert "Domain=" not in header and "Secure" not in header
        assert app.state.sessions.pair_hash is None
        assert isinstance(app.state.sessions.session_hash, bytes)
        assert (await client.post("/board-api/session", json={"pairing_code": code})).status_code == 401
        assert (await client.get("/board-api/session")).json()["expires_in_seconds"] == SESSION_SECONDS
        # A copied invalid opaque cookie cannot authenticate.
        good = cookie
        client.cookies.set(COOKIE, secrets.token_urlsafe(32), domain="127.0.0.1", path="/board-api")
        assert (await client.get("/board-api/session")).status_code == 401
        client.cookies.set(COOKIE, good, domain="127.0.0.1", path="/board-api")
        clock[0] = SESSION_SECONDS
        assert (await client.get("/board-api/session")).status_code == 401
        assert (await client.post("/board-api/session", json={"pairing_code": code})).status_code == 401
    scenario(tmp_path, run)


def test_logout_revokes_copied_cookie(tmp_path):
    async def run(client, code, token, clock, app):
        await pair(client, code)
        saved = client.cookies.get(COOKIE)
        result = await client.delete("/board-api/session")
        assert result.status_code == 200 and not result.json()["authenticated"]
        assert "Max-Age=0" in result.headers["set-cookie"]
        assert (await client.get("/board-api/session", headers={"Cookie": COOKIE + "=" + saved})).status_code == 401
    scenario(tmp_path, run)


@pytest.mark.parametrize("body", [{}, {"pairing_code": "bad"}, {"pairing_code": 42},
    {"pairing_code": "x" * 43, "operator": True}, {"pairing_code": "x" * 1000}])
def test_invalid_bootstrap_is_bounded(tmp_path, body):
    async def run(client, *args):
        result = await client.post("/board-api/session", json=body)
        assert result.status_code == 422
        assert "pairing_code" not in result.text
        assert result.headers["Cache-Control"] == "private, no-store"
    scenario(tmp_path, run)


def test_pairing_expiry_and_guess_budget(tmp_path):
    async def run(client, code, token, clock, app):
        clock[0] = PAIR_SECONDS
        assert (await client.post("/board-api/session", json={"pairing_code": code})).status_code == 401
        clock[0] = 0
        for _ in range(32):
            assert (await client.post("/board-api/session", json={"pairing_code": secrets.token_urlsafe(32)})).status_code == 401
        assert (await client.post("/board-api/session", json={"pairing_code": code})).status_code == 401
    scenario(tmp_path, run)


@pytest.mark.parametrize("headers", [
    {"Origin": "http://evil.invalid"}, {"Origin": "null"}, {"Origin": "http://localhost:8001"},
    {"Host": "evil.invalid"}, {"Host": "127.0.0.1:8002"}, {"X-Relay-Board": ""},
    {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}])
def test_cross_origin_blocked_for_bootstrap_reads_and_logout(tmp_path, headers):
    async def run(client, code, *args):
        await pair(client, code)
        for method, path, body in (("POST", "session", {"pairing_code": code}),
                ("GET", "operator/jobs", None), ("DELETE", "session", None)):
            result = await client.request(method, "/board-api/" + path, headers=headers, json=body)
            assert result.status_code == 403
            assert "access-control-allow-origin" not in result.headers
        assert (await client.get("/board-api/session")).status_code == 200
    scenario(tmp_path, run)


def test_missing_origin_csrf_preflight_and_safe_get(tmp_path):
    async def run(client, code, *args):
        client.headers.pop("Origin")
        assert (await client.post("/board-api/session", json={"pairing_code": code})).status_code == 403
        client.headers["Origin"] = ORIGIN
        await pair(client, code)
        client.headers.pop("Origin")
        assert (await client.get("/board-api/session")).status_code == 200
        assert (await client.delete("/board-api/session")).status_code == 403
        response = await client.options("/board-api/session", headers={"Origin": "http://evil.invalid",
            "Access-Control-Request-Headers": "x-relay-board", "Access-Control-Request-Method": "POST"})
        assert response.status_code == 403 and "access-control-allow-origin" not in response.headers
    scenario(tmp_path, run)


@pytest.mark.parametrize("header", ["Authorization", "X-Worker-Session"])
def test_browser_bearer_or_worker_headers_never_authorize(tmp_path, header):
    async def run(client, code, token, *args):
        result = await client.post("/board-api/session", json={"pairing_code": code}, headers={header: token})
        assert result.status_code == 401 and token not in result.text
        await pair(client, code)
        assert (await client.get("/board-api/operator/jobs", headers={header: token})).status_code == 401
    scenario(tmp_path, run)


@pytest.mark.parametrize("status", [401, 404, 409, 422, 503])
def test_proxy_errors_are_byte_exact_no_leaked_headers(tmp_path, status):
    raw = json.dumps({"error": {"code": "backend_example", "message": "backend_example", "retryable": status == 503,
        "outcome": "not_committed" if status == 503 else "rejected", "request_id": "upstream-request", "details": {}}}).encode()
    observed = []
    def upstream(request):
        observed.append(request)
        return httpx.Response(status, content=raw, headers={"Content-Type": "application/json", "X-Request-Id": "upstream-request",
            "Set-Cookie": "upstream=unsafe", "X-Secret": "unsafe", "Cache-Control": "public"})
    async def run(client, code, token, *args):
        await pair(client, code)
        result = await client.get("/board-api/operator/jobs?limit=2&cursor=a%2Bb", headers={"X-Forwarded-Host": "evil.invalid"})
        assert result.status_code == status and result.content == raw
        assert result.headers["x-request-id"] == "upstream-request"
        assert result.headers["cache-control"] == "private, no-store"
        assert "set-cookie" not in result.headers and "x-secret" not in result.headers
        assert len(observed) == 1
        sent = observed[0]
        assert sent.url.raw_path == b"/v1/operator/jobs?limit=2&cursor=a%2Bb"
        assert sent.headers["authorization"] == "Bearer " + token
        assert not any(header in sent.headers for header in ("cookie", "origin", "x-forwarded-host", "x-worker-session"))
        assert token not in result.text
    scenario(tmp_path, run, upstream)


@pytest.mark.parametrize("fault", ["offline", "malformed", "schema", "oversized", "redirect", "secret", "escaped_secret", "request_id_secret"])
def test_dependency_failure_and_secret_echo_fail_closed(tmp_path, fault):
    captured = []
    def upstream(request):
        token = request.headers["authorization"][7:]
        if fault == "offline": raise httpx.ConnectError("private upstream config", request=request)
        body = {"as_of": "2026-10-03T12:00:00+00:00", "snapshot_scope": "request_repeatable_read", "items": [], "next_cursor": None}
        raw = json.dumps(body).encode()
        status = 200
        rid = "upstream-request"
        if fault == "malformed": raw = b"not-json"
        if fault == "schema": raw = b'{"items":[]}'
        if fault == "oversized": raw = b" " * (MAX_RESPONSE + 1)
        if fault == "redirect": status = 302
        if fault in ("secret", "escaped_secret"):
            body["next_cursor"] = token
            raw = json.dumps(body).encode()
            if fault == "escaped_secret":
                raw = raw.replace(token.encode(), "".join("\\u%04x" % ord(c) for c in token).encode())
        if fault == "request_id_secret": rid = token
        captured.append(token)
        return httpx.Response(status, content=raw, headers={"Content-Type": "application/json", "X-Request-Id": rid,
            "Location": "http://evil.invalid"})
    async def run(client, code, token, *args):
        await pair(client, code)
        result = await client.get("/board-api/operator/jobs")
        assert result.status_code == 503
        assert result.json()["error"]["code"] == ("browser_backend_unavailable" if fault == "offline" else "browser_upstream_invalid")
        assert token not in result.text and token not in str(dict(result.headers))
        assert "private upstream config" not in result.text and "location" not in result.headers
    scenario(tmp_path, run, upstream)


def test_allowlist_no_control_or_arbitrary_target(tmp_path):
    observed = []
    def upstream(request):
        observed.append(request)
        return httpx.Response(503)
    async def run(client, code, *args):
        await pair(client, code)
        for path in ("jobs/abc/cancel", "artifacts/abc/content", "workers/abc/claim", "http://evil.invalid", "../health", "health"):
            result = await client.get("/board-api/operator/" + path)
            assert result.status_code == 404
        assert (await client.post("/board-api/operator/jobs", json={})).status_code == 404
        assert (await client.get("/board-api/operator/jobs?" + "x" * 4097)).status_code == 422
        assert (await client.get("/board-api/operator/%6Aobs")).status_code == 422
        assert observed == []
    scenario(tmp_path, run, upstream)


def test_secret_containing_json_escaped_punctuation_is_rejected(tmp_path):
    token = secrets.token_urlsafe(32) + '"\\'
    def upstream(request):
        return httpx.Response(200, json={"as_of": "2026-10-03T12:00:00+00:00",
            "snapshot_scope": "request_repeatable_read", "items": [], "next_cursor": token},
            headers={"X-Request-Id": "upstream-request"})
    async def run(client, code, *args):
        await pair(client, code)
        result = await client.get("/board-api/operator/jobs")
        assert result.status_code == 503 and token not in result.text
    scenario(tmp_path, run, upstream, operator_token=token)


@pytest.mark.parametrize("fault", ["duplicate", "nonfinite", "missing_scope"])
def test_malformed_wire_contract_cannot_be_repaired_by_defaults(tmp_path, fault):
    def upstream(request):
        body = {"as_of": "2026-10-03T12:00:00+00:00", "snapshot_scope": "request_repeatable_read",
                "items": [], "next_cursor": None}
        if fault == "missing_scope": body.pop("snapshot_scope")
        raw = json.dumps(body).encode()
        if fault == "duplicate": raw = raw[:-1] + b',"next_cursor":null}'
        if fault == "nonfinite": raw = raw.replace(b"null", b"NaN")
        return httpx.Response(200, content=raw, headers={"Content-Type": "application/json", "X-Request-Id": "upstream-request"})
    async def run(client, code, *args):
        await pair(client, code)
        response = await client.get("/board-api/operator/jobs")
        assert response.status_code == 503 and response.json()["error"]["code"] == "browser_upstream_invalid"
    scenario(tmp_path, run, upstream)


def test_html_assets_config_isolation(tmp_path):
    async def run(client, code, token, *args):
        (tmp_path / "index.html").write_text('<html><script src="/board/assets/entry.js"></script></html>')
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets/entry.js").write_text("console.log('safe')")
        (tmp_path / "assets/tainted.js").write_text(token)
        for path in ("/board-connect", "/board-connect.js", "/board", "/board/jobs/example", "/board/assets/entry.js"):
            response = await client.get(path)
            assert response.status_code == 200
            assert all(secret not in response.text for secret in (token, code))
            assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        for path in ("/.env", "/openapi.json", "/v1/operator/capabilities", "/board/assets/source.js.map", "/board/assets/.env"):
            assert (await client.get(path)).status_code == 404
        assert (await client.get("/board/assets/tainted.js")).status_code == 503
        (tmp_path / "index.html").write_text(token)
        assert (await client.get("/board")).status_code == 503
    scenario(tmp_path, run)


@pytest.mark.parametrize("url", ["https://127.0.0.1:8000", "http://localhost:8000", "http://0.0.0.0:8000", "http://127.0.0.1:8000/",
    "http://user@127.0.0.1:8000", "http://127.0.0.1:8000?target=evil", "http://127.0.0.1", "http://127.0.0.1:99999"])
def test_config_rejects_remote_dns_and_ambiguous_urls(url):
    token = secrets.token_urlsafe(32)
    with pytest.raises(ValueError): Config(url, ORIGIN, Path("."), token)
    with pytest.raises(ValueError): Config("http://127.0.0.1:8000", url, Path("."), token)


def test_server_config_is_selective_no_interpolation_or_repr_leak(tmp_path):
    token = secrets.token_urlsafe(32)
    file = tmp_path / ".env"
    file.write_text(f"RELAY_OPERATOR_TOKEN={token}\nPOSTGRES_PASSWORD=unused\nS3_RUNTIME_SECRET_KEY=unused\n")
    config = Config.from_file(file, "http://127.0.0.1:8000", ORIGIN, tmp_path)
    assert config.operator_token == token and token not in repr(config)
    assert not hasattr(config, "POSTGRES_PASSWORD")
    file.write_text("RELAY_OPERATOR_TOKEN=${SHOULD_NOT_INTERPOLATE}\n")
    with pytest.raises(ValueError): Config.from_file(file, "http://127.0.0.1:8000", ORIGIN, tmp_path)
