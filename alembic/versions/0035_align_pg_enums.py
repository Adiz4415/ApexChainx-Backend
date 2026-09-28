# raw-sql-allowed
"""Align Postgres enum types with the ORM's member sets.

The 0003-era enums carried fewer values than the application now writes, and
create_all-built test databases (which define enums from the Python classes)
never noticed:

- webhookdeliverystatus: add dead_letter, breaker_open (BE-086 dead-letter
  handling and circuit-breaker deferral write these states).
- webhookevent: add sla.warning (the warning event is emitted alongside
  violation/resolved).

Values are appended with IF NOT EXISTS semantics via a DO block, so the
migration is safe to run on databases that already contain the labels.

Revision ID: 0035_align_pg_enums
Revises: 0034_close_orm_migration_drift
Create Date: 2026-09-27
"""

from alembic import op
from sqlalchemy import text

revision = "0035_align_pg_enums"
down_revision = "0034_close_orm_migration_drift"
branch_labels = None
depends_on = None

# (enum type, new label) pairs. PostgreSQL has no ALTER TYPE ... ADD VALUE IF
# NOT EXISTS before 9.x-era installs in some environments, so use a guarded DO
# block that is idempotent regardless.
_STATEMENTS = [
    ("webhookdeliverystatus", "dead_letter"),
    ("webhookdeliverystatus", "breaker_open"),
    ("webhookevent", "sla.warning"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for enum_type, label in _STATEMENTS:
        conn.execute(text(_do_add_label(enum_type, label)))


def _do_add_label(enum_type: str, label: str) -> str:
    safe_type = enum_type.replace("'", "''")
    safe_label = label.replace("'", "''")
    return _DO_ADD_LABEL.format(enum_type=safe_type, label=safe_label)


_DO_ADD_LABEL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum e
        JOIN pg_type t ON e.enumtypid = t.oid
        WHERE t.typname = '{enum_type}' AND e.enumlabel = '{label}'
    ) THEN
        ALTER TYPE {enum_type} ADD VALUE '{label}';
    END IF;
END
$$;
"""


def downgrade() -> None:
    # Enum labels cannot be removed without type recreation; the added values
    # are benign when unused, so downgrade is a no-op.
    pass
