"""Indexes for bounded operator catalogue, participation and event reads.

Revision ID: 0003_operator_indexes
Revises: 0002_readiness
No authority columns, constraints, triggers or grants change.
"""

from alembic import op

revision = "0003_operator_indexes"
down_revision = "0002_readiness"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_jobs_operator_created", "jobs", ["created_at", "id"])
    op.create_index("ix_jobs_operator_status_created", "jobs", ["status", "created_at", "id"])
    op.create_index("ix_attempts_operator_worker", "attempts", ["worker_session_id", "id"])
    op.create_index("ix_events_operator_attempt", "events", ["job_id", "attempt_id", "seq"])


def downgrade():
    for name, table in (("ix_events_operator_attempt", "events"), ("ix_attempts_operator_worker", "attempts"),
                        ("ix_jobs_operator_status_created", "jobs"), ("ix_jobs_operator_created", "jobs")):
        op.drop_index(name, table_name=table)
