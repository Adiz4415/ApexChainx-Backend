"""Record the SLA policy version in analytics snapshot metadata (issue #567).

Snapshots materialize aggregates computed under a specific policy, but the row
carried no record of which version produced the numbers, so a snapshot taken
before a config publish was indistinguishable from one taken after. Adding a
nullable ``policy_version`` column stamps each snapshot with the highest
version across severities at snapshot time (``sla_config_history`` is the
ledger, #272). Existing rows predate the column and keep NULL.

Revision ID: 0032_snapshot_policy_version
Revises: 0031_merge_open_branches
Create Date: 2026-09-26
"""

import sqlalchemy as sa

from alembic import op

revision = "0032_snapshot_policy_version"
down_revision = "0031_merge_open_branches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sla_analytics_snapshots",
        sa.Column("policy_version", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sla_analytics_snapshots", "policy_version")
