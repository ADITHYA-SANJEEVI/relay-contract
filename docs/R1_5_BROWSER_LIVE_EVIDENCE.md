# R1.5 / BV10 browser-live operator seam evidence

Status: **PASS** for the trusted local installation seam. No production multi-user
authentication, Frontend Slice 2 or R2 implementation is claimed.

## Checkpoint and commits

- Branch: `r1.5/browser-live-seam`.
- Starting SHA: `d707dd92237d90c8e2aca0e0aa4b8d0e738af8f0`.
- Startup tree was clean; all three required startup conditions passed.
- Implementation: `0ed52d367945fbda3d3d4a22998d950245f0dda8`,
  `Implement Relay BV10 browser-live seam` (17 files).
- Evidence is the separate `Record Relay BV10 evidence` commit containing this
  document; its SHA is supplied in the final report.
- No push, merge or tag action was performed.

Frozen annotated-tag objects and peeled targets were checked unchanged:

| Ref | Tag object | Peeled commit |
|---|---|---|
| `relay-frontend-slice1-final` | `7083518def4cbef1d298a8a44382812b4735a615` | `8aab14010b8e4f653fadb470c4a83b00dd3ab814` |
| `relay-r1-operator-visibility` | `235b83b2b977055d00a91091cb3d70dfa97a6adb` | `d707dd92237d90c8e2aca0e0aa4b8d0e738af8f0` |

## Architecture and threat model

The selected design was recorded in [BROWSER_LIVE_SEAM.md](BROWSER_LIVE_SEAM.md)
before implementation, after reading the product specification, API/operator
contracts, R1 and frozen frontend evidence, actual frontend adapter/domain/runtime
configuration and backend auth. It follows the approved FastAPI compiled `/board`
asset direction: browser -> same-origin `/board-api` on a separate local BFF ->
server-injected bearer -> unchanged backend `/v1/operator` GET surface.

The trusted OS account/private workspace, reviewed assets, BFF and backend are
trusted. Other browser origins, request inputs and unvalidated upstream responses
are untrusted. The BFF has no DB/store/worker credential or persistence client.
Only 16 exact R1 GET routes are allowlisted; no generic proxy or control route.
Separate process restart revokes sessions without disturbing backend execution.

Rejected: privileged bearer plus browser CORS, broadening backend auth to cookies,
unauthenticated localhost proxy, SSR migration, unnecessary IdP/viewer-admin roles.
Same-origin XSS can use authenticated reads despite HttpOnly. Cookies are host/path
scoped, not port scoped; other local services and Vite development code must be
trusted. Protect OS-profile ACLs/private workspace and cloud sync.

## Session, origin and secret ownership

One random 256-bit pairing code, 120-second expiry, one successful use, at most
32 guesses per process; one random 256-bit opaque session with absolute 30-minute
expiry. Hashes are retained in volatile process state. Logout/restart revoke old
cookies; consumed/expired code cannot renew. Multiple tabs may share the session.
Code is delivered only in an ignored local `.cache` file, never HTML/config/URL/
logs. Normal shutdown removes it; hard termination can leave a stale file requiring
exact-file removal after confirming the old process stopped, or a new private path.
Exclusive creation prevents overwrites. Windows inherits profile ACLs; POSIX uses 0600.

Cookie: HttpOnly, SameSite=Strict, host-only, Path=/board-api, Max-Age=1800.
Secure=false is confined to explicit loopback HTTP. Remote/TLS/proxy and multi-worker
deployment are unsupported, not a configuration flip.

Every API request requires exact Host and `X-Relay-Board: 1`, rejects foreign Origin
and Fetch Metadata; POST/DELETE require explicit exact Origin. GET can omit Origin
while retaining the other guards/Strict cookie. JSON bootstrap, non-simple header
and absence of CORS/preflight grants protect login/logout and read CSRF. No wildcard
CORS, forwarded-header trust, ambient proxy or redirect following. Vite preserves
Host/Origin/Fetch Metadata using `changeOrigin:false`; both listeners bind loopback.

Only `RELAY_OPERATOR_TOKEN` is selected from the server env file, without dotenv
interpolation; other backend credentials are discarded. Config repr/startup errors
suppress values; access logs are disabled, and upstream exceptions are not logged.
The browser receives safe session status/R1 contracts, no bearer API/env/storage.
Detailed operation/configuration/error contracts: [BROWSER_LIVE_SEAM.md](BROWSER_LIVE_SEAM.md).

## Test results

**133 distinct Python tests passed**: 50 new BV10 tests and 83 existing regressions.
**45 frontend tests passed**: 19 new and all 26 frozen tests. Repeated subset/combined
runs are not added to these distinct totals.

| Gate / suite | Result |
|---|---|
| BV10 boundary tests | 47 passed |
| BV10 real-service tests | 3 passed |
| R1 operator visibility | 21 passed |
| Backend integration | 28 passed |
| Publication/security | 25 passed |
| Backend unit | 9 passed |
| Frontend Vitest | 5 files, 45 passed |
| Typecheck / lint | Both exit 0, no errors/warnings |
| Production build | Exit 0, 1976 modules; pre/post secret guard passed on 41 client files |
| Screenshot gate | 14 of 14 PNG captures in ignored `.cache/bv10-screenshots` |
| Python compileall / offline uv lock check | Both exit 0; 40 resolved packages; no lock changes |
| Working/staged diff checks | Exit 0 |

Commands used (build before real compiled-asset smoke):

```powershell
# From frontend:
npm.cmd run typecheck
npm.cmd run lint
npm.cmd test
npm.cmd run build
$env:RELAY_SCREENSHOT_DIR = 'C:\Users\adith\OneDrive\Desktop\relay-contract\.cache\bv10-screenshots'
npm.cmd run screenshots
# From repository root:
.\.venv\Scripts\python.exe -m pytest tests/browser_seam tests/operator_visibility tests/integration tests/publication tests/unit -q --tb=short
.\.venv\Scripts\python.exe -m pytest tests/browser_seam -q --tb=short
.\.venv\Scripts\python.exe -m pytest tests/browser_seam/test_live.py -q --tb=short
.\.venv\Scripts\python.exe -m compileall -q src/relay/browser scripts/serve_board.py tests/browser_seam
.\.venv\Scripts\uv.exe lock --check --offline --cache-dir .cache/uv
git diff --check
```

Combined regression run: 128 passed in 574.70 seconds (45 then-current BV10 cases
plus 83 regressions). Final BV10 coverage grew to 50 and passed in 69.05 seconds.
The three real-service tests, subsequently strengthened to fetch actual compiled
HTML/JS/CSS, passed again in 55.49 seconds. Frontend full run: 45 passed in 13.60
seconds; final build: 53.13 seconds. After strengthening escaped-secret checks,
both build-guard tests passed again (2/2). Existing React Router future-flag notices
remain informational. No baseline test was removed/weakened.

Initial runs exposed new harness issues: Windows cross-identity temp ACLs and
transient log locks, wrong worker-secret wire format, reused consumed mock Response,
and a Vite base-path HTTP test URL. Those were corrected without changing baseline
tests. Final proxy parsing also rejects duplicate/nonfinite JSON and missing
observation scope instead of repairing malformed responses with schema defaults.
No unresolved failure remains. Existing auth/API/core behavior did not change,
so the conditional full execution fault/concurrency rerun was not needed; this
pass does not claim every repository test was rerun.

## Real-service HTTP smoke and security

Used real healthy Compose PostgreSQL 18.6 and pinned MinIO, migrated disposable
databases, generated credentials and actual API/BFF/Vite subprocesses on isolated
loopback ports. No SQLite or mocked authority; no retained-installation deployment.
Harnesses terminate only their own child processes and clean their exact temp roots.

- Established job/claim/verified-output/accepted-result fixture before the comparison
  snapshot. Unauthenticated reads rejected 401; one-use bootstrap created the cookie.
- All 16 R1 reads succeeded, preserving as_of, request_repeatable_read, string
  bigints, accepted authority, definition scope, event direction/frontier and cursors.
- Direct backend BV10 stayed DEFERRED; authenticated BFF BV10 was AVAILABLE. All
  other capability records/database revision matched. Availability is active BFF
  discovery, not documentation or an assertion of DB/store health.
- Every authority table was identical before/after reads. Pinned verification first
  succeeded; deleting only the test's exact object version then produced FAILED
  storage/version verification, preserved ACCEPTED authority, and changed no DB rows.
- Worker credentials/operator Authorization could not create browser authority.
  Real backend 404/422 and wrong server bearer 401 kept typed meanings; offline
  backend produced explicit 503, never empty jobs/fixture data.
- New process rejected old code/copied cookie and accepted fresh pairing. Unit
  boundary tests independently covered logout, expiry, replay and copied-cookie revocation.
- Actual Vite configuration proxied pairing, capabilities/jobs, served `/board/`
  and denied the BFF private env through its filesystem route.
- Actual BFF-served compiled HTML, JS, CSS, pairing HTML/JS, JSON, headers and logs
  contained no generated backend operator credential; pairing code was not echoed.

Focused tests cover missing/invalid/expired bootstrap/session; cookie attributes;
hash retention; guess/body/query/response bounds; Host/Origin/header/Fetch Metadata;
mandatory mutation Origin and denied preflight; worker separation; allowlist/control
denial; no client/forwarding/cookie headers upstream; upstream Set-Cookie stripping;
redirect refusal; unreachable/malformed/schema-invalid/duplicate/nonfinite responses;
missing snapshot scope/request ID; unsafe request IDs; plain/Unicode/JSON-punctuation
secret echoes; HTML/asset secret refusal; selective config/repr and strict loopback URLs.
Controlled HTTP transport faults complement real services, not replace them.

Backend 401/404/409/422/503 body/status/request ID were byte-exact through the proxy.
Sensitive responses override unsafe upstream caching with private/no-store. Successful
non-capability bytes remain unchanged. Capabilities reserialization overlays exactly
BV10 while retaining observation/revision/upstream auth facts. Frontend tests preserve
typed errors, request IDs, timestamps, string bigints, cursors and verification failure,
and prove explicit fixture choice/no silent fallback.

Build guard passed pre/post compilation; negative tests reject client secret variables
and configured secret bytes without printing values. Precommit credential comparison
found no actual configured credential in 17 changed files plus 4 compiled artifacts
(21 files; values withheld). No static real credential fixtures, new dependency,
client secret config, storage write or bearer-in-URL mechanism was introduced.
Final comparison including this evidence also passed: 22 changed/client artifact
files, with no credential values printed.

## Preservation and exact files

Diff against the required checkpoint found no changes in existing backend auth/API/
R1 implementation, control, DB, gateway/recovery; no migration or execution/control
API, state transition, lease/retry/publication/accepted-result/worker/event change.
BFF has no persistence/DML. Existing provider/views/components/adapters/domain and
Scenario A-H fixtures are untouched, as are historical evidence/screenshots.
New screenshot F/H were visually inspected: integrity failure retains acceptance;
history gap remains explicit. Compiled CSS `index-BcYzwCCM.css` and JS
`index-BSHnA98O.js` retain the frozen evidence's content hashes. HTML asset base paths
change; the new transport is not imported by the frozen app.

| Category | Files |
|---|---|
| Authoritative docs | `docs/API.md`, `docs/OPERATOR_API.md`, `docs/BROWSER_LIVE_SEAM.md` |
| Frontend infrastructure | `frontend/package.json`, `frontend/vite.config.ts`, `frontend/scripts/capture-screenshots.js`, `frontend/scripts/check-client-secrets.js`, `frontend/src/api/browserTransport.ts` |
| Frontend tests | `frontend/src/api/browserTransport.test.ts`, `frontend/tests/client-secret-boundary.test.ts` |
| Separate BFF runtime/launcher | `scripts/serve_board.py`, `src/relay/browser/__init__.py`, `src/relay/browser/app.py`, `src/relay/browser/session.py` |
| BFF tests | `tests/browser_seam/conftest.py`, `tests/browser_seam/test_boundary.py`, `tests/browser_seam/test_live.py` |
| Evidence commit only | `docs/R1_5_BROWSER_LIVE_EVIDENCE.md` |

Generated bundles, local pairing/env/log files and fresh screenshots are ignored,
not committed. No historical evidence was rewritten.

## Limitations and next-pass readiness

Single trusted local process/session, fixed expiry, no renewal/persistence,
loopback HTTP only; no remote/TLS/enterprise identity/RBAC/multi-worker claim.
Same-origin XSS/OS compromise remains outside concealment guarantees. In-flight
reads can finish after logout; later requests reject. Buffering is bounded to 8 MiB;
use pagination. No subscription freshness/global snapshot/durable incident claim.

Slice 2 may deliberately consume `browserTransport` for authenticated discovery,
catalogue and all allowlisted R1 reads. Provider/screen wiring remains its own pass;
translate R1 links to seam reads, retain explicit fixture choice and preserve authority,
observation/cursor/error meanings. Pairing does not make frozen screens consume live
data. BV02/BV11 remain deferred. R2 was not begun; read access alone does not establish
report/controller/release readiness.
