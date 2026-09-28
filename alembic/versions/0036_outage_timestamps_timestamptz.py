# raw-sql-allowed
"""Convert the remaining naive outages timestamps to timestamptz.

0026b converted only updated_at; detected_at, resolved_at, and created_at were
left as ``timestamp without time zone`` while the ORM declares
``DateTime(timezone=True)``. Reading such rows produced naive datetimes, which
the Outage pydantic model rejects — every list request 500'd. Stored values
were written with datetime.now(UTC), so interpret them as UTC when converting
(no instant shift).

Revision ID: 0036_outage_timestamps_timestamptz
Revises: 0035_align_pg_enums
Create Date: 2026-09-28
"""

from alembic import op

revision = "0036_outage_timestamps_timestamptz"
down_revision = "0035_align_pg_enums"
depends_on = None
branch_labels = None

_COLUMNS = ("detected_at", "resolved_at", "created_at")


def upgrade() -> None:
    for column in _COLUMNS:
        op.execute(
            f"ALTER TABLE outages ALTER COLUMN {column} TYPE timestamptz "
            f"USING {column} AT TIME ZONE 'UTC'"
        )


def downgrade() -> None:
    for column in _COLUMNS:
        op.execute(
            f"ALTER TABLE outages ALTER COLUMN {column} TYPE timestamp "
            f"USING {column} AT TIME ZONE 'UTC'"
        )
