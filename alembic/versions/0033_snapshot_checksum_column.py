"""Add the missing checksum column to sla_analytics_snapshots.

The ORM (app/models/orm/sla_snapshot.py) declares ``checksum`` (String(64),
NOT NULL) and uses it for snapshot tamper detection, but migration 0007 never
created the column and no later migration added it. Test databases built with
``Base.metadata.create_all`` never noticed; any database built through the
Alembic chain breaks snapshot writes with UndefinedColumn. This restores
parity between the models and the migrated schema.

Existing rows are backfilled with the checksum their own contents produce
(the same algorithm ``SLAAnalyticsSnapshotORM.compute_checksum`` uses), so
integrity verification is valid immediately after upgrade. Rows predating
migration 0032 backfill with ``policy_version = NULL``, which the checksum
algorithm accepts.

Revision ID: 0033_snapshot_checksum_column
Revises: 0032_snapshot_policy_version
Create Date: 2026-09-27
"""

import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0033_snapshot_checksum_column"
down_revision: str | None = "0032_snapshot_policy_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _compute_checksum(row: dict) -> str:
    data = {
        "snapshot_key": row["snapshot_key"],
        "total_outages": row["total_outages"],
        "total_violations": row["total_violations"],
        "total_rewards": row["total_rewards"],
        "total_penalties": row["total_penalties"],
        "net_payout": row["net_payout"],
        "avg_mttr": row["avg_mttr"],
        "policy_version": row["policy_version"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()


def upgrade() -> None:
    conn = op.get_bind()
    op.add_column(
        "sla_analytics_snapshots",
        sa.Column("checksum", sa.String(64), nullable=False, server_default=""),
    )
    rows = conn.execute(
        sa.text(
            "SELECT id, snapshot_key, total_outages, total_violations, total_rewards, "
            "total_penalties, net_payout, avg_mttr, policy_version, created_at "
            "FROM sla_analytics_snapshots WHERE checksum = ''"
        )
    ).mappings()
    for row in rows:
        conn.execute(
            sa.text("UPDATE sla_analytics_snapshots SET checksum = :c WHERE id = :id"),
            {"c": _compute_checksum(dict(row)), "id": row["id"]},
        )
    # The ORM always supplies checksum on insert; drop the temporary default.
    op.alter_column("sla_analytics_snapshots", "checksum", server_default=None)


def downgrade() -> None:
    op.drop_column("sla_analytics_snapshots", "checksum")
