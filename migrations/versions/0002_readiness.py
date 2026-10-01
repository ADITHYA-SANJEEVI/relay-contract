"""Read-only migration revision for runtime readiness; no control authority.

Revision ID: 0002_readiness
Revises: 0001_persistence
"""

from alembic import op

revision = "0002_readiness"
down_revision = "0001_persistence"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE VIEW relay_schema_version WITH (security_barrier=true) AS SELECT version_num FROM alembic_version")
    op.execute("GRANT SELECT ON relay_schema_version TO relay_runtime")


def downgrade():
    op.execute("DROP VIEW relay_schema_version")
