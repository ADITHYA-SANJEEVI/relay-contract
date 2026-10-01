"""Contract persistence foundation; reviewable frozen SQL, including guards.

Revision ID: 0001_persistence
Revises: None
"""

from pathlib import Path

from alembic import op

revision = "0001_persistence"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    script = Path(__file__).with_name("0001_persistence.sql").read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(script, execution_options={"no_parameters": True})
    guards = Path(__file__).with_name("0001_guards.sql").read_text(encoding="utf-8")
    op.get_bind().exec_driver_sql(guards, execution_options={"no_parameters": True})


def downgrade():
    # Destructive by definition; tests use a disposable DB, never M0 volumes.
    op.execute("ALTER TABLE partitions DROP CONSTRAINT fk_partitions_latest_attempt")
    for name in (
        "request_receipts", "worker_events", "events", "accepted_results",
        "artifacts", "attempts", "partition_inputs", "partitions",
        "job_inputs", "input_artifacts", "workers", "jobs", "scheduler_state",
    ):
        op.execute(f"DROP TABLE {name}")
    for signature in (
        "relay_check_consistency()", "relay_guard_manifest_insert()",
        "relay_guard_state()", "relay_guard_immutable()", "relay_reject_history_change()",
    ):
        op.execute(f"DROP FUNCTION {signature}")
