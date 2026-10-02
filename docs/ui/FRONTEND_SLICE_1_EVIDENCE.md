# RELAY CONTROL BOARD — FRONTEND IMPLEMENTATION SLICE 1 EVIDENCE

**Document Date:** 3 October 2026
**Repository:** `relay-contract`
**Branch:** `frontend/control-board-v1`
**Starting SHA:** `70d8393b5aab0e99fa39d5b3843019e3f94285a8`
**Original Slice 1 Commit SHA:** `acb09c2512f9f1f07151f79bf8823627e7ed4e70`
**Closure Starting SHA:** `acb09c2512f9f1f07151f79bf8823627e7ed4e70`
**Closure Commit SHA:** recorded by Git history; intentionally not self-referential in this document.
**Specification Source of Truth:** `docs/RELAY_CONTROL_BOARD_PRODUCT_SPEC_V1.md`

---

## 1. Executive Summary

Frontend Slice 1 of the Relay Control Board has been implemented adhering strictly to the product specification (`docs/RELAY_CONTROL_BOARD_PRODUCT_SPEC_V1.md`). The Control Board serves as an **execution investigation console** designed around the core question:
> *"Which attempt produced the accepted result, and what happened to the other attempts?"*

All backend authority semantics, PostgreSQL invariants, generation fencing rules, publication gates, and artifact verification distinctions have been preserved without any backend modifications.

---

## 2. Hard Backend Preservation Boundary

Mechanically confirmed:
- **`src/relay/**`:** Zero modifications (`git diff --stat src/relay` returned empty).
- **Backend Migrations / Schema:** Zero modifications.
- **Backend State-Machine / Concurrency Tests:** Zero modifications.
- **Backend Authentication / Protocol:** Zero modifications.

Allowed modifications made:
- Added `frontend/**` (React, TypeScript, Vite, TanStack Query/Table, Tailwind CSS, Lucide, Vitest, Puppeteer).
- Added `docs/ui/**` (Evidence document and captured visual QA screenshots).
- Minimal root `.gitignore` modification to exclude `frontend/node_modules/`, `frontend/dist/`, `frontend/coverage/`.

---

## 3. Four-Dimensional Semantic Model & Invariants Verified

The frontend strictly isolates four separate dimensions:

| Dimension | Question | Implementation & Display |
|---|---|---|
| **1. Recorded Lifecycle** | What committed state exists in the database? | `RecordedStatusBadge` displaying durable enums (`QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `CANCELLED`). `STALE` is never displayed as an attempt lifecycle enum. |
| **2. Observed Ownership** | Does the recorded attempt appear within lease/deadline relative to observation time? | `ObservationBadge` evaluating lease/deadline against server/fixture observation clock. If attempt is `ACTIVE` and deadline is past: renders **"Deadline passed · awaiting settlement"** (never committed `EXPIRED`). Worker liveness displays `FRESH` vs `SUSPECT` (30s rule) independently from worker lifecycle (`REGISTERED`, `DRAINING`, `STOPPED`). |
| **3. Artifact Verification** | Were exact bytes and schema hashes cryptographically verified? | `ArtifactStatusBadge` displaying `RESERVED`, `VERIFIED`, `REJECTED`, or `Unavailable`. Invariant: `VERIFIED != ACCEPTED`. Expired attempt can retain a `VERIFIED` artifact. |
| **4. Result Authority** | Which artifact was actually accepted for this partition? | `AuthorityPanel` with green 3px authority rail, explicit accepted partition, attempt, generation, artifact ID, and publication fingerprint. An integrity read failure displays a separate warning while preserving the green authority relation. |

---

## 4. Package & Dependency Choices

- **Runtime Framework:** React 18.3.1
- **Language:** TypeScript 5.7.3 (`target: ES2022`, `strict: true`, `noUnusedLocals: true`, `noEmit: true`)
- **Build Tool:** Vite 6.2.0
- **Routing:** React Router DOM 6.29.0
- **Query Cache:** TanStack React Query 5.67.1
- **Icons:** Lucide React (consistent 16px outline set)
- **Styling:** CSS Custom Properties for Relay design tokens + Tailwind CSS 3.4.17 (with PostCSS / Autoprefixer)
- **Testing:** Vitest 3.0.6, JSDOM 26.0.0, `@testing-library/react` 16.2.0, `@testing-library/dom` 10.4.0, `@testing-library/jest-dom` 6.6.3, `@testing-library/user-event` 14.6.1
- **Visual QA Automation:** Puppeteer 24.3.0

---

## 5. Implemented Routes & Navigation

| Route | View | Description |
|---|---|---|
| `/board` | `OverviewView` | Overview console with Open Job by ID input, exact UUID validation, and Needs Attention active work summary. |
| `/board/jobs` | `JobsListView` | Jobs catalogue. Displays explicit BV01 capability gap in live baseline mode; displays deterministic scenarios in fixture mode. |
| `/board/jobs/:jobId` | `JobDetailView` | Flagship screen. Compact summary strip, Execution tab (~60% partition table, ~40% partition inspector with anchored AuthorityPanel and generation stack), Activity tab (bounded sequence chronology), Results tab (explicit verification policy), and Definition tab (immutable descriptor). |
| `/board/workers` | `WorkersView` | Fleet console. Displays explicit BV07 capability gap in live baseline mode; displays deterministic worker sessions with independent lifecycle and liveness in fixture mode. |
| `/board/lab` | `FailureLabView` | Recorded Failure Lab evidence. Displays Scenario 1 (G4 stale completion after G5 acceptance), invariant `INVARIANT-PUBLICATION-01`, expected vs observed side-by-side, and correlated action/event ledgers. |
| `/board/evidence` | `EvidenceView` | Validation manifests index for M2 and M3 milestones with exact repository commit SHAs. |

---

## 6. Deterministic Synthetic Scenarios (A through H)

The persistent banner **`SYNTHETIC DEMO DATA`** is visibly rendered on every synthetic screen with a scenario selector:

- **Scenario A (G5 Accepted / G4 Stale Rejection):**
  Partition 0 has G5 `SUCCEEDED` + `VERIFIED` + `ACCEPTED` (authoritative relation). G4 attempt remains `EXPIRED`, artifact remains `VERIFIED`, and publication is `REJECTED · stale_generation`.
- **Scenario B (Deadline Passed / Awaiting Settlement):**
  Partition 1 has an `ACTIVE` attempt whose lease expired prior to observation time. Status remains `ACTIVE` with badge `"Deadline passed · awaiting settlement"`. Authority panel renders neutral `"No accepted result"`.
- **Scenario C (RUNNING Job containing FAILED Partition):**
  Job status is `RUNNING`, partition 3 is terminal `FAILED`, partition counts reflect 1 FAILED, 2 RUNNING, 1 READY. Header notes: *"Work continues; failed partitions will make final outcome FAILED"*.
- **Scenario D (FAILED Job with Partial Accepted Results):**
  Job status is `FAILED`, partial accepted count is 2 / 4 (50%). Header notes: *"Job failed · partial accepted results retained"*. Acceptance progress bar remains visible.
- **Scenario E (No Accepted Result):**
  Partition 2 has no accepted result. Renders neutral `AuthorityPanel` without green rail; does not promise eventual success.
- **Scenario F (Integrity Read Failure preserving Authority):**
  Partition 3 has an accepted result relation, but explicit later content read encountered storage checksum mismatch. Green authority rail remains intact with separate integrity warning banner.
- **Scenario G (Disconnected / Last-Known State):**
  Connection failure retains last successful observation timestamp (`01:58:30Z`), marks API unreachable, and preserves last known snapshot.
- **Scenario H (Backend Capability Unavailable):**
  Explicitly renders `CapabilityUnavailable` state explaining the missing read contract (`GET /v1/operator/partitions/{id}`), refusing to display fake zero rows.

---

## 7. Live Backend Integration & Visibility Gaps

### Actual Routes Integrated (Live Mode):
- `GET /health/live`: Checked for API process reachability.
- `GET /health/ready`: Checked for readiness observation and database revision (`0002_readiness`).
- `GET /v1/jobs/{id}`: Consumed for job status, partition counts, and next event sequence.
- `GET /v1/jobs/{id}/partitions`: Consumed with server cursor and status filter.
- `GET /v1/jobs/{id}/events`: Consumed with forward cursor `after_seq`.
- `GET /v1/jobs/{id}/results`: Consumed only on explicit operator action (*"Load Verified Accepted Manifests"*).

### Explicit Backend Visibility Gaps Handled:
- **BV01 Jobs Catalogue:** `GET /v1/operator/jobs` is absent. Renders honest capability gap; jobs opened by exact UUID.
- **BV03 Partition Attempt History:** `GET /v1/operator/partitions/{id}` is absent. Baseline partition read provides only latest attempt and accepted artifact ID.
- **BV07 Worker Fleet:** `GET /v1/operator/workers` is absent. Worker-self endpoints require worker secrets and are not called from frontend.
- **BV09 Definition Read:** Detailed definition read contract absent; definition hash and submission parameters presented.

---

## 8. Automated Test Suite Results

Command: `npm test` (`vitest run`)
Test Files: `tests/authority-invariants.test.tsx`, `tests/interaction-ux.test.tsx`
**Total Tests:** 24 passed (24 total) — 100% PASS

1. `VERIFIED artifact remains distinct from ACCEPTED authority`: PASS
2. `G4 EXPIRED, VERIFIED, stale publication rejection while G5 is ACCEPTED`: PASS
3. `deadline-passed ACTIVE remains ACTIVE`: PASS
4. `FAILED job retains partial accepted output`: PASS
5. `RUNNING job can contain FAILED partition`: PASS
6. `no accepted result renders neutral AuthorityPanel`: PASS
7. `unknown authority differs from no accepted result`: PASS
8. `missing capability differs from empty result`: PASS
9. `disconnected mode retains last-known observation`: PASS
10. `unknown differs from zero`: PASS
11. `selected row styling differs from accepted authority styling`: PASS
12. `keyboard can select/inspect partition`: PASS
13. `fixture mode displays: SYNTHETIC DEMO DATA`: PASS
14. `network failure does NOT automatically switch to fixture mode`: PASS
15. `integrity-read failure preserves accepted relation`: PASS
16. `IDs copied exactly`: PASS
17. `unsupported enum does not map to success`: PASS
18. `generation stack preserves independent lifecycle/artifact/publication dimensions`: PASS

---

## 9. Static Validation & Build Results

- **TypeScript Typecheck:** `npm run typecheck` (`tsc --noEmit`) -> **PASS** (Exit code 0, 0 errors)
- **ESLint:** `npm run lint` (`eslint src`) -> **PASS** (Exit code 0, 0 warnings/errors)
- **Production Build:** `npm run build` (`tsc -b && vite build`) -> **PASS** (Exit code 0)
  - `dist/index.html`: 0.47 kB (gzip: 0.30 kB)
  - `dist/assets/index-DV19rb3t.css`: 22.18 kB (gzip: 5.26 kB)
  - `dist/assets/index-DUaWIhSK.js`: 317.72 kB (gzip: 88.76 kB)

---

## 10. Visual QA & Screenshot Matrix

Automated Puppeteer script (`npm run screenshots`) captured 10 deterministic states into `docs/ui/screenshots/`:

| Screenshot File | Viewport | Target / Scenario | Status |
|---|---|---|---|
| `01_job_detail_1440x900_scenario_a.png` | 1440×900 | Scenario A: G5 Accepted / G4 Stale Rejection, split view | Captured |
| `02_job_detail_1366x768_scenario_b_deadline_passed.png` | 1366×768 | Scenario B: Partition 1 Deadline passed / awaiting settlement | Captured |
| `03_job_detail_1280x800_running_with_failed_partition.png` | 1280×800 | Scenario C: RUNNING job with Partition 3 FAILED | Captured |
| `04_job_detail_1024x768_failed_partial_results.png` | 1024×768 | Scenario D: FAILED job with 50% partial accepted outputs | Captured |
| `05_job_detail_768x1024_tablet.png` | 768×1024 | Tablet stacked summary & table view | Captured |
| `06_activity_events_chronology.png` | 1440×900 | Activity tab: bounded sequence chronology & renewals | Captured |
| `07_results_verified_manifests.png` | 1440×900 | Results tab: cryptographic verification notice & manifests | Captured |
| `08_failure_lab_recorded_evidence.png` | 1440×900 | Failure Lab: recorded evidence, expected vs observed | Captured |
| `09_workers_fleet_observation.png` | 1440×900 | Workers: independent lifecycle and liveness observations | Captured |
| `10_overview_open_job.png` | 1440×900 | Overview: Open Job by ID and Needs Attention list | Captured |

---

## 11. Accessibility & Responsive Verification

- **Semantic Landmarks:** `<main id="main-content">`, `<nav aria-label="...">`, `<aside>`, `<header role="banner">`.
- **Keyboard Navigation:** Skip link to main content, visible focus rings (`:focus-visible`), table row selection on `Enter` / `Space`, tab switching with ARIA roles (`role="tab"`, `role="tabpanel"`).
- **Non-Color Signals:** Every semantic status includes distinct text, explicit icon, and dedicated tooltip. Color is never the sole differentiator.
- **Screen Reader Announcements:** Hidden screen reader prefixes distinguish `Recorded status:`, `Observation:`, and `Accepted result:`.
- **Reduced Motion:** `@media (prefers-reduced-motion: reduce)` disables all animations and transitions.
- **Responsive Target Checking:** Verified across 1440x900, 1366x768, 1280x800, 1024x768, and 768x1024.
  A separate documented 200% zoom verification was not performed in this closure pass.

---

## 12. Known Limitations & Deferred by Design

- **Workers Mutation Controls:** Drain, stop, restart, and kill actions remain strictly disabled/deferred to preserve security boundaries.
- **Live Failure Lab Controller:** Interactive fault injection controller is deferred pending separate local controller security gate.
- **Job Cancellation:** Documented backend route is absent; no cancel mutation is exposed in Slice 1.
- **Backend Visibility Gaps:** Global jobs enumeration, full attempt history, and operator worker fleet reads remain declared as gaps until addressed by an independent backend milestone.
