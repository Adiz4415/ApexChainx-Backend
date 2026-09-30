# raw-sql-allowed
"""Record SLA policy version in analytics snapshots.

Adds sla_analytics_snapshots.policy_version, a composite marker of every
severity's policy version at snapshot time (e.g. "critical1.high1.low1.medium1").
Nullable: rows written before #567 have no recorded version.

Also adds the snapshot ``checksum`` column the ORM has had since commit
674c61a but for which no migration was ever written — without it every
freshly migrated database crashed on snapshot creation.

Revision ID: 0033_snapshot_policy_version
Revises: 0032_outage_status_detected_at_index, 0031_webhook_url_events_unique
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0033_snapshot_policy_version"
down_revision: Union[str, Sequence[str], None] = (
    "0032_outage_status_detected_at_index",
    "0031_webhook_url_events_unique",
    "218a9af9d890",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sla_analytics_snapshots", sa.Column("policy_version", sa.String(255), nullable=True))
    # Schema-drift fix: ORM checksum column had no matching migration.
    op.add_column(
        "sla_analytics_snapshots",
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("sla_analytics_snapshots", "checksum")
    op.drop_column("sla_analytics_snapshots", "policy_version")
