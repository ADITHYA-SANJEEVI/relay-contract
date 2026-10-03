"""Strict loopback BFF: opaque browser session -> existing R1 bearer reads."""

import json
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from dotenv import dotenv_values
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing import Literal

from relay.operator import models as m
from .session import COOKIE, SESSION_SECONDS, Sessions

MAX_RESPONSE = 8 * 1024 * 1024
PREFIX = "/board-api"
IDENTITY = r"[A-Za-z0-9-]{1,64}"
ROUTES = tuple((re.compile(pattern), model) for pattern, model in (
    ("capabilities", m.Capabilities), ("jobs", m.JobPage),
    (f"jobs/{IDENTITY}", m.JobSnapshot),
    (f"jobs/{IDENTITY}/partitions", m.PartitionPage),
    (f"partitions/{IDENTITY}", m.PartitionSnapshot),
    (f"partitions/{IDENTITY}/history", m.PartitionSnapshot),
    (f"attempts/{IDENTITY}", m.AttemptSnapshot),
    (f"artifacts/{IDENTITY}", m.ArtifactSnapshot),
    (f"artifacts/{IDENTITY}/verification", m.VerificationSnapshot),
    (f"jobs/{IDENTITY}/result-metadata", m.ResultPage),
    (f"jobs/{IDENTITY}/events", m.EventPage),
    ("workers", m.WorkerPage), (f"workers/{IDENTITY}", m.WorkerSnapshot),
    (f"workers/{IDENTITY}/attempts", m.ParticipationPage),
    (f"workers/{IDENTITY}/events", m.WorkerEventPage),
    (f"jobs/{IDENTITY}/definition", m.DefinitionSnapshot),
))


def loopback_url(value):
    parts = urlsplit(value)
    try:
        valid = (parts.scheme == "http" and parts.hostname == "127.0.0.1"
                 and parts.port is not None and 1 <= parts.port <= 65535
                 and not parts.username and not parts.password
                 and not parts.path and not parts.query and not parts.fragment
                 and value == f"http://127.0.0.1:{parts.port}")
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("explicit_loopback_origin_required")
    return value


@dataclass(frozen=True)
class Config:
    backend: str
    origin: str
    assets: Path
    operator_token: str = field(repr=False)

    def __post_init__(self):
        loopback_url(self.backend)
        loopback_url(self.origin)
        if (not 32 <= len(self.operator_token) <= 4096
                or not self.operator_token.isascii()
                or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in self.operator_token)):
            raise ValueError("invalid_server_operator_config")

    @classmethod
    def from_file(cls, env_file, backend, origin, assets):
        # No interpolation or inherited environment; other backend credentials are discarded.
        token = dotenv_values(env_file, interpolate=False).get("RELAY_OPERATOR_TOKEN")
        if not token:
            raise ValueError("missing_server_operator_config")
        return cls(backend, origin, Path(assets).resolve(), token)


class Pairing(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    pairing_code: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: str
    message: str
    retryable: bool
    outcome: Literal["committed", "not_committed", "unknown", "rejected"]
    request_id: str | None
    details: dict


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: ErrorDetail


def contains_secret(value, secret):
    if isinstance(value, dict):
        return any(contains_secret(key, secret) or contains_secret(item, secret) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_secret(item, secret) for item in value)
    return secret in str(value)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_upstream_field")
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError("invalid_upstream_number")


CONNECT_HTML = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Relay local connection</title><h1>Relay local connection</h1>
<p>Enter the one-use code from the trusted local pairing file. This grants R1 read access
for 30 minutes. The Control Board still uses its frozen fixtures.</p>
<form id="pair"><label>Local pairing code <input id="code" type="password"
autocomplete="off" maxlength="43" required></label><button>Pair</button></form>
<button id="logout">Disconnect</button><p id="status" role="status"></p>
<a href="/board">Open Control Board</a><script src="/board-connect.js"></script></html>"""
CONNECT_JS = """const status = document.getElementById('status');
async function call(method, body) {
  try {
    const r = await fetch('/board-api/session', {method, credentials:'same-origin',
      cache:'no-store', headers:{'X-Relay-Board':'1','Content-Type':'application/json'},
      ...(body ? {body:JSON.stringify(body)} : {})});
    const data = await r.json();
    status.textContent = r.ok ? (method === 'DELETE' ? 'Disconnected.' :
      'Local read session connected. Control Board fixtures are unchanged.') : data.error.code;
  } catch { status.textContent = 'Local connection unavailable.'; }
}
document.getElementById('pair').addEventListener('submit', e => {
  e.preventDefault(); const input = document.getElementById('code');
  const code = input.value; input.value = ''; call('POST', {pairing_code:code});
});
document.getElementById('logout').addEventListener('click', () => call('DELETE'));
call('GET');"""


def create_app(config, pairing_code, *, clock=None, upstream_transport=None):
    sessions = Sessions(pairing_code, **({"clock": clock} if clock else {}))
    client = httpx.AsyncClient(base_url=config.backend, trust_env=False,
                              follow_redirects=False, timeout=httpx.Timeout(15, connect=2),
                              transport=upstream_transport)

    @asynccontextmanager
    async def lifespan(app):
        yield
        sessions.logout()
        await client.aclose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.sessions = sessions
    app.state.upstream = client

    def error(request, code, status):
        return JSONResponse({"error": {"code": code, "message": code,
            "retryable": status == 503, "outcome": "not_committed" if status == 503 else "rejected",
            "request_id": request.state.request_id, "details": {}}}, status_code=status)

    @app.middleware("http")
    async def boundary(request, call_next):
        request.state.request_id = str(uuid4())
        path = request.url.path
        api = path == PREFIX or path.startswith(PREFIX + "/")
        # Guard Host even for static assets; no wildcard host or forwarded-header trust.
        if request.headers.get("host") != urlsplit(config.origin).netloc:
            response = error(request, "browser_origin_rejected", 403)
        elif api and (request.headers.get("X-Relay-Board") != "1"
                or request.headers.get("origin", config.origin) != config.origin
                or (request.method in ("POST", "DELETE") and request.headers.get("origin") != config.origin)
                or request.headers.get("sec-fetch-site", "same-origin") != "same-origin"):
            response = error(request, "browser_origin_rejected", 403)
        elif api and ("authorization" in request.headers or "x-worker-session" in request.headers):
            response = error(request, "browser_credentials_rejected", 401)
        elif api and (len(request.scope.get("query_string", b"")) > 4096
                or b"%" in request.scope.get("raw_path", b"")
                or config.operator_token.encode() in request.scope.get("query_string", b"")):
            response = error(request, "invalid_request", 422)
        else:
            try:
                response = await call_next(request)
            except Exception:
                # Never log exceptions, request URLs, headers, cookies or upstream config.
                response = error(request, "browser_internal_error", 500)
        response.headers.setdefault("X-Request-Id", request.state.request_id)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'")
        return response

    def authenticated(request):
        return sessions.valid(request.cookies.get(COOKIE))

    @app.post(PREFIX + "/session")
    async def pair(request: Request):
        if request.url.query or request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            return error(request, "invalid_request", 422)
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 256:
                return error(request, "invalid_request", 422)
        try:
            body = Pairing.model_validate_json(bytes(content))
        except ValidationError:
            return error(request, "invalid_request", 422)
        token = sessions.pair(body.pairing_code)
        if token is None:
            return error(request, "browser_auth_required", 401)
        response = JSONResponse(sessions.snapshot())
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                            secure=False, samesite="strict", path=PREFIX)
        return response

    @app.api_route(PREFIX + "/session", methods=["GET", "DELETE"])
    async def session(request: Request):
        if request.url.query:
            return error(request, "invalid_request", 422)
        if not authenticated(request):
            return error(request, "browser_auth_required", 401)
        if request.method == "GET":
            return JSONResponse(sessions.snapshot())
        sessions.logout()
        response = JSONResponse({"authenticated": False, "mode": "local_read_session"})
        response.delete_cookie(COOKIE, path=PREFIX, httponly=True, samesite="strict")
        return response

    @app.get(PREFIX + "/operator/{path:path}")
    async def operator(request: Request, path: str):
        if not authenticated(request):
            return error(request, "browser_auth_required", 401)
        model = next((model for pattern, model in ROUTES if pattern.fullmatch(path)), None)
        if model is None:
            return error(request, "browser_route_unavailable", 404)
        if request.headers.get("content-length", "0") != "0" or "transfer-encoding" in request.headers:
            return error(request, "invalid_request", 422)
        query = request.scope.get("query_string", b"").decode("ascii", errors="strict")
        target = "/v1/operator/" + path + ("?" + query if query else "")
        try:
            async with client.stream("GET", target, headers={
                    "Authorization": "Bearer " + config.operator_token,
                    "Accept": "application/json"}) as upstream:
                data = bytearray()
                async for chunk in upstream.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE:
                        return error(request, "browser_upstream_invalid", 503)
                raw = bytes(data)
                if upstream.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                    return error(request, "browser_upstream_invalid", 503)
                decoded = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
                # Inspect decoded JSON too, so Unicode-escaped secret echoes cannot leak.
                rid = upstream.headers.get("x-request-id", "")
                if (contains_secret(decoded, config.operator_token) or config.operator_token.encode() in raw
                        or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", rid)
                        or config.operator_token in rid):
                    return error(request, "browser_upstream_invalid", 503)
                if upstream.status_code == 200:
                    if not isinstance(decoded, dict) or not {"as_of", "snapshot_scope"} <= decoded.keys():
                        return error(request, "browser_upstream_invalid", 503)
                    model.model_validate_json(raw)
                    if path == "capabilities":
                        if not {"api_revision", "authentication"} <= decoded.keys():
                            return error(request, "browser_upstream_invalid", 503)
                        matches = [item for item in decoded["capabilities"] if item["id"] == "BV10_BROWSER_AUTH"]
                        if len(matches) != 1:
                            return error(request, "browser_upstream_invalid", 503)
                        matches[0].update(state="AVAILABLE", routes=[PREFIX + "/session", PREFIX + "/operator/capabilities"],
                            reason="Active local BFF: HttpOnly read session; backend bearer stays server-side.")
                        raw = json.dumps(decoded, separators=(",", ":")).encode()
                elif 400 <= upstream.status_code <= 599:
                    ErrorEnvelope.model_validate_json(raw)
                else:
                    return error(request, "browser_upstream_invalid", 503)
                return Response(raw, status_code=upstream.status_code, media_type="application/json",
                                headers={"X-Request-Id": rid})
        except httpx.HTTPError:
            return error(request, "browser_backend_unavailable", 503)
        except (ValueError, ValidationError, RecursionError):
            return error(request, "browser_upstream_invalid", 503)

    @app.get("/board-connect")
    async def connect():
        return HTMLResponse(CONNECT_HTML)

    @app.get("/board-connect.js")
    async def connect_script():
        return Response(CONNECT_JS, media_type="text/javascript")

    @app.get("/board")
    @app.get("/board/{path:path}")
    async def board(request: Request, path: str = ""):
        root = config.assets.resolve()
        if path.startswith("assets/"):
            candidate = (root / path).resolve()
            if (not candidate.is_relative_to(root / "assets") or not candidate.is_file()
                    or any(part.startswith(".") for part in Path(path).parts)
                    or candidate.suffix not in (".js", ".css", ".svg", ".png", ".woff", ".woff2")):
                return error(request, "browser_route_unavailable", 404)
        else:
            candidate = (root / "index.html").resolve()
            if not candidate.is_relative_to(root):
                return error(request, "browser_route_unavailable", 404)
        if not candidate.is_file():
            return error(request, "browser_assets_unavailable", 503)
        # Reject tainted built assets, never serve server config or source maps.
        if config.operator_token.encode() in candidate.read_bytes():
            return error(request, "browser_assets_invalid", 503)
        return FileResponse(candidate)

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    async def unavailable(request: Request, path: str):
        return error(request, "browser_route_unavailable", 404)

    return app
