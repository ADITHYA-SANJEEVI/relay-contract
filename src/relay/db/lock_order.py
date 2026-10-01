"""Code-level contract for later transition services, not a locking framework.

Acquire PostgreSQL row locks in this order, skipping categories not needed.
Never acquire an earlier category afterward. Partition order is ascending ordinal;
attempt order is ascending generation. See docs/DATABASE.md for operation exceptions.
"""

LOCK_ORDER = (
    "scheduler_state",
    "job",
    "partitions (ascending ordinal)",
    "attempts (ascending generation)",
    "worker",
    "artifact",
    "receipt",
)
