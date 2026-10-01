# Relay architecture contract — v1.0

Prepared 2 October 2026 from the two supplied Relay briefs. This is a documentation-only design baseline. No runtime has been implemented or benchmarked. The design fixes the safety contract; implementation remains gated by the selected object store's capability tests and review of these documents.

Start with [docs/SPEC.md](docs/SPEC.md), then follow its reading order. The nine documents include the architecture diagram, technology choices, schema and transactional pseudocode, state machines, failure outcomes, APIs, invariant-driven tests, reproducible fault/benchmark methodology, risk register and sequential milestones.

Key decisions: at-most-one accepted result per immutable partition; fresh DB-time fencing under locks; version-pinned artifacts; explicit cancellation ordering; bounded retries and absolute attempt lifetimes; no claims of universal exactly-once execution.

This checkout is locally version-controlled. A private remote has not been created or pushed as part of this design delivery. The implementation plan makes that a prerequisite at M0.
