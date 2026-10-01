# Accepted M0 architecture clarifications

Date: 2026-10-02. Architecture contract: Relay V1, version 1.0, with accepted amendments A1–A3.

- **A1:** Renewal, fresh owner failure, live-attempt artifact reservation and new publication require job RUNNING. First claim atomically moves QUEUED→RUNNING; an ACTIVE attempt therefore cannot create authority for a QUEUED job. Historical accepted-result replay still acknowledges acceptance after cancellation.
- **A2:** SPEC.md defines one canonical **live attempt ownership** predicate. All four operations reference it; none may weaken it. One `clock_timestamp()` sample is taken after the final potentially blocking authoritative-state lock. This prevents drift in ownership, generation and deadline checks.
- **A3:** Post-acceptance reads verify the exact pinned object version. Corruption yields explicit integrity failure, structured logs and appropriate metrics, while accepted metadata remains immutable. No substitution or automatic terminal recomputation. Durable, deduplicated, queryable integrity-incident persistence is deferred beyond V1; no V1 schema/API promise or M0 table implements it.

Affected documents: SPEC.md, INVARIANTS.md, STATE_MACHINES.md, DATABASE.md, FAILURE_MODEL.md, API.md and TEST_PLAN.md. The failure-model storage risk now explicitly requires architecture review for backend replacement when the M0 gate fails, as directed by the M0 task.

These changes strengthen/clarify the existing safety contract rather than redefining Relay's primary guarantee: at most one accepted result per partition of an immutable job version. No runtime safety mechanisms are implemented by this documentation amendment.
