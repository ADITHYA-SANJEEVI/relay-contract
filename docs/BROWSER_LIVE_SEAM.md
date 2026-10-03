# BV10 local browser-live seam

## Architecture decision (recorded before implementation)

The product specification section 27 approves compiled React/Vite assets under
`/board` served by FastAPI, with a scoped browser auth adapter. Vite is a static
SPA, not an existing SSR identity server. Use a small **separate localhost
FastAPI frontend/BFF process**: browser -> same-origin `/board-api` -> server-held
operator bearer -> existing localhost `/v1/operator` backend. The BFF serves the
frozen compiled SPA at `/board`; it does not wire any screen to runtime data.

The backend's tested bearer boundary and read contracts remain unchanged. The
BFF forwards GET only to the 16 shipped R1 read routes; no generic proxy, worker
credential, execution/control endpoint, caller-chosen upstream or storage URL.
No database/store credential is needed by the BFF. This follows the approved
FastAPI asset-serving direction without adding Next.js or an enterprise IdP.

Rejected: browser bearer/CORS exposes the privileged secret; adding cookie auth
directly to backend operator authentication broadens that tested boundary;
no-auth localhost reads allow unrelated websites to target the local service;
SSR migration/RBAC is unnecessary. Separate frontend and backend processes let
BFF restarts revoke browser sessions without restarting execution services.

## Trust model and session lifecycle

This is one trusted local installation, not remote/multi-user production auth.
The OS account, backend and BFF are trusted. Browser content is untrusted until
paired; an authenticated same-origin script can exercise read access but cannot
retrieve the bearer. HttpOnly is not protection against same-origin XSS using
the session; trusted built assets, origin guards and CSP remain required.

The BFF loads only the operator bearer from a server-only env file; target URL,
exact browser origin and compiled asset location are startup configuration.
Targets/origins must use explicit `http://127.0.0.1:<port>` loopback URLs. No
wildcard origins, DNS names, remote targets, redirects or ambient HTTP proxies.
The local HTTP cookie is HttpOnly, SameSite=Strict, host-only, scoped to
`/board-api`, with Max-Age and an absolute server expiry. Secure is false only
for this explicit loopback HTTP profile. Remote HTTP/TLS/proxy deployment is
unsupported and requires a separate security review, not a configuration flip.

Startup creates one cryptographically random 256-bit pairing code, valid for
120 seconds and one successful use. It is supplied only to the trusted local
launcher/file, never HTML, URLs, JS config or logs. At most one browser session
exists per BFF process (multiple tabs share that cookie). Pairing creates a
separate random opaque 256-bit session; only hashes are retained server-side.
The session has a fixed 30-minute maximum, no sliding renewal/persistence.
Invalid/expired/replayed pairing and invalid/expired sessions fail closed.
Logout revokes the session and clears its cookie. Restart revokes all old codes
and sessions and issues a new pairing code; expired/logout sessions require
restart/re-pair. No browser operator-password field or viewer/admin hierarchy.

## Browser boundary and response preservation

All `/board-api` requests require exact configured Host, same-origin Origin
(mandatory for POST/DELETE), same-origin Fetch Metadata when present, and the
non-simple `X-Relay-Board: 1` header. Browser GET may omit Origin; Host, custom
header, SameSite and Fetch Metadata still gate it. Cross-site requests cannot
set the custom header without preflight, and this service grants no CORS.
Bootstrap/logout use JSON and explicit Origin, preventing login/logout CSRF.
Pairing codes are bounded in request body; they are not a CSRF bypass.

Browser Authorization, X-Worker-Session, cookies, forwarding headers and arbitrary
upstream headers are never passed upstream. BFF injects its configured bearer
server-side. Backend status, typed error envelope, request ID, decimal bigints,
observation time, snapshot scope, acceptance, cursors and verification result
are preserved. Auth failures never become empty data or fixture mode. Sensitive
responses are private/no-store. Upstream failures/malformed or oversized JSON
produce opaque typed dependency errors; secret-containing output fails closed.

Only proxied capabilities changes: BV10_BROWSER_AUTH becomes AVAILABLE with
explicit BFF routes/reason. Direct backend discovery retains DEFERRED; it is
truthful about its bearer-only surface. All other capabilities and observation
fields remain backend facts. This context-dependent capability avoids claiming
the seam is running merely because code/documentation is installed.

## Frontend boundary

Add an unused typed browser transport/session/connection primitive for Slice 2,
an exact same-origin development proxy and safe compiled-asset configuration.
Provide a tiny standalone pairing page separate from the frozen Control Board.
No views, providers, existing adapter, Scenario A-H data, synthetic mode or
inspection behavior are changed. Session/live reachability/capability states are
separate; callers must deliberately choose fixture mode, never fall back to it.

## Shipped HTTP contract

| Browser route | Authentication / response |
|---|---|
| `GET /board-connect`, `/board-connect.js` | Public local pairing surface; no code/credential embedded |
| `GET /board`, `/board/*` | Compiled fixture SPA and bounded assets; no server configuration/source maps |
| `POST /board-api/session` | JSON `{pairing_code: "<one-use-local-code>"}`; one-use pairing, sets HttpOnly cookie; no session token in JSON |
| `GET /board-api/session` | Cookie required; `{authenticated:true, mode:"local_read_session", expires_in_seconds:integer}` |
| `DELETE /board-api/session` | Cookie + explicit Origin required; revokes session, clears cookie, returns authenticated=false |
| `GET /board-api/operator/<R1 path>` | Cookie required; exact 16-route allowlist from [OPERATOR_API.md](OPERATOR_API.md), existing query/response schemas |

The pairing body is at most 256 bytes, requires JSON, forbids extra fields and
requires a 43-character URL-safe code. There are at most 32 well-formed pairing
guesses per process. Query parameters on session routes reject 422. No refresh,
session-list/admin, password, arbitrary URL, or bearer retrieval route exists.
Upstream queries are bounded to 4,096 bytes; encoded proxy paths and GET bodies
reject 422. Upstream decoded responses are bounded to 8 MiB and validated against
R1's frozen Pydantic models. Larger observations fail explicitly; Slice 2 should
use bounded pages. Only JSON body/status and validated X-Request-Id pass through;
upstream cookies, redirects and arbitrary headers do not. All responses, including
authentication errors and assets, are `private, no-store` with nosniff, no-referrer
and a same-origin CSP/frame-ancestors none.

Local missing/invalid/expired session or unavailable pairing returns 401
`browser_auth_required`; unsupported credential headers return 401
`browser_credentials_rejected`. Origin/Host/header/Fetch Metadata rejection is
403 `browser_origin_rejected`. Invalid bootstrap/query is 422 `invalid_request`.
Unshipped routes/methods return 404 `browser_route_unavailable`. Upstream network/
timeout failure is 503 `browser_backend_unavailable`; malformed JSON/schema,
oversized responses, redirects, missing/unsafe request IDs and credential echoes
are 503 `browser_upstream_invalid`. Assets missing/tainted return explicit 503.
Unexpected BFF errors are opaque 500 `browser_internal_error`. All use the existing
typed error envelope and generated BFF request ID. Valid backend errors (including
401/404/409/422/503) retain their bytes, status, details and upstream request ID.
All ordinary successful read bytes are preserved too; only capabilities is
reserialized to overlay exactly BV10. Absolute R1 links in payloads remain backend
contract links; Slice 2 must select allowlisted BFF reads, not blindly navigate
content URLs or substitute a verification link for accepted authority.

## Configuration and local operation

SERVER-ONLY: the existing backend's `RELAY_OPERATOR_TOKEN` in a private env file.
The BFF reads that field without dotenv interpolation and discards database,
storage and worker configuration. It never inherits a token from the frontend
environment. The backend target, browser origin, asset directory and pairing
file are launcher configuration, not browser inputs. Config repr and startup
errors suppress secret values. Uvicorn access logging/forwarded-header trust are
disabled; the BFF logs neither requests nor upstream exceptions.

CLIENT-SAFE: `/board-api` paths, R1 schemas/capability IDs, session status and
remaining lifetime. There is no `VITE_*` token, injected HTML setting or token
argument on `browserTransport`. The build guard rejects server credential names,
client secret environment variables and configured credential bytes (including
ordinary JSON/JS escapes) in source/config/public/built assets. It logs paths and
counts only. This is a practical accidental-leak check, not a proof against
arbitrarily obfuscated malicious source; trusted reviewed frontend code remains
part of the model.

From the repository root (PowerShell), with the established backend already
listening on `127.0.0.1:8000` and its operator credential in the server env file:

```powershell
Set-Location frontend
npm.cmd run build
Set-Location ..
.\.venv\Scripts\python.exe scripts\serve_board.py --env-file .env
```

Open `http://127.0.0.1:8001/board-connect`. Read the one-use code from the private
local `.cache/board-pairing/code` file in the trusted OS account, then paste it
into that page within 120 seconds. Never use the backend bearer in this form.
Pairing creates read transport access; opening `/board` still shows the frozen
synthetic UI. Keep backend and BFF processes separate. Logout, expiry or restarting
the BFF requires fresh pairing. Normal shutdown removes the pairing file; a hard
crash/Windows forced termination can leave a stale file. After confirming that
the prior BFF is stopped, remove only that exact stale file or choose a new
private `.cache` path with `--pairing-file`. Exclusive creation rejects overwrite
and concurrent launch; stale codes/cookies never authorize a new process.

Development uses this exact origin, without CORS:

```powershell
.\.venv\Scripts\python.exe scripts\serve_board.py --env-file .env --origin http://127.0.0.1:3000
# Separate terminal, from frontend:
npm.cmd run dev
```

Open `http://127.0.0.1:3000/board-connect`, then `/board/`. Vite binds loopback with
strict port 3000 and proxies `/board-api` and `/board-connect*` to BFF port 8001,
preserving Host, Origin and Fetch Metadata (`changeOrigin:false`). Browser cookie
and API remain on the frontend origin. `localhost`, other ports and wildcard
origins reject. Existing legacy development health/API proxies are retained for
the frozen adapter; they inject no credential and are not the Slice 2 auth path.
Vite dev/preview are development tools, not production servers; compiled `/board`
deployment is the BFF profile above. Default Vite filesystem guards deny server
env files; the real development-proxy test verifies that denial.

## Slice 2 consumption and explicit limitations

Use the unused `frontend/src/api/browserTransport.ts` primitive: pair/session/
logout, capabilities/jobs, bounded `read<T>(R1-relative-path, URLSearchParams)`.
It uses `credentials:same-origin`, `cache:no-store`, redirect rejection and the
custom header, with no bearer API or storage writes. Returned R1 `as_of` is the
backend observation, never a replacement browser clock. `probe('fixture')` is an
explicit synthetic choice and makes no request. `probe('live')` requires available
BV10 and BV01 plus a successful jobs read, and returns `live-connected`,
`authentication-required`, `backend-unavailable` or `capability-unavailable`.
Errors retain their typed code/status/request ID; an upstream 401 with an active
browser session may mean server credential configuration needs correction.
Failure never yields fixture mode or an invented empty catalogue. Capability
states use R1's AVAILABLE/UNAVAILABLE/DEFERRED/UNSUPPORTED vocabulary.

Only Slice 2 may wire these responses into providers/screens. It must preserve
snapshot scopes, string bigints, cursors, authority versus latest-attempt evidence
and verification failure independently; no control/content/worker-secret route
is available through this seam. BV02/BV11 and R2 remain deferred.

This is single-process, single-session, trusted OS-account, loopback HTTP only.
No multi-worker BFF, persistence, renewal, remote deployment, IdP, roles or TLS
production auth claim. Windows pairing files inherit OS-profile ACLs (POSIX gets
0600); operators must protect that account/private workspace, including cloud
sync. Cookies are host/path scoped, not port scoped: unrelated local services
and the Vite dev server must also be trusted. Same-origin XSS can use read access
despite HttpOnly. In-flight reads authorized before logout/expiry can finish;
subsequent requests reject. The proxy validates bounded responses in memory, does
not claim polling/subscription freshness, and does not cache or store observations.

Validation and preservation evidence: [R1_5_BROWSER_LIVE_EVIDENCE.md](R1_5_BROWSER_LIVE_EVIDENCE.md).
