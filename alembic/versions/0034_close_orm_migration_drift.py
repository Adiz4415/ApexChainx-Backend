# raw-sql-allowed
"""Close the ORM/migration drift for sla_results, jobs, sla_disputes, webhook_deliveries.

A drift audit (ORM metadata vs. the migrated schema) found ten columns that the
application code reads and writes but that no migration ever created. Test
databases built with ``Base.metadata.create_all`` never noticed; any database
built through the Alembic chain fails on the first touch of these columns with
UndefinedColumn:

- sla_results: policy_version, threshold_source, reason_code, decision_trace
- jobs: progress_details, partial_results, per_item_errors
- sla_disputes: baseline_sla_result_id, proposed_sla_result_id
- webhook_deliveries: dead_lettered_at

Existing rows predate these features and get NULL / defaults.

Revision ID: 0034_close_orm_migration_drift
Revises: 0033_snapshot_checksum_column
Create Date: 2026-09-27
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0034_close_orm_migration_drift"
down_revision = "0033_snapshot_checksum_column"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- sla_results ---
    op.add_column("sla_results", sa.Column("policy_version", sa.String(50), nullable=False, server_default="1.0"))
    op.add_column("sla_results", sa.Column("threshold_source", sa.String(50), nullable=False, server_default="config"))
    op.add_column("sla_results", sa.Column("reason_code", sa.String(50), nullable=True))
    op.add_column("sla_results", sa.Column("decision_trace", sa.Text(), nullable=True))
    # The ORM declares the runtime default; clear the backfill default afterwards.
    op.alter_column("sla_results", "policy_version", server_default=None)
    op.alter_column("sla_results", "threshold_source", server_default=None)

    # --- jobs (JSONB to match the 0026 conversion of payload/result) ---
    op.add_column("jobs", sa.Column("progress_details", JSONB(), nullable=True))
    op.add_column("jobs", sa.Column("partial_results", JSONB(), nullable=True))
    op.add_column("jobs", sa.Column("per_item_errors", JSONB(), nullable=True))

    # --- sla_disputes ---
    op.add_column(
        "sla_disputes",
        sa.Column("baseline_sla_result_id", sa.Integer(), sa.ForeignKey("sla_results.id"), nullable=True),
    )
    op.add_column(
        "sla_disputes",
        sa.Column("proposed_sla_result_id", sa.Integer(), sa.ForeignKey("sla_results.id"), nullable=True),
    )

    # --- webhook_deliveries ---
    # Plain DateTime (naive) to match the table's existing columns and the ORM.
    op.add_column("webhook_deliveries", sa.Column("dead_lettered_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("webhook_deliveries", "dead_lettered_at")
    op.drop_column("sla_disputes", "proposed_sla_result_id")
    op.drop_column("sla_disputes", "baseline_sla_result_id")
    op.drop_column("jobs", "per_item_errors")
    op.drop_column("jobs", "partial_results")
    op.drop_column("jobs", "progress_details")
    op.drop_column("sla_results", "decision_trace")
    op.drop_column("sla_results", "reason_code")
    op.drop_column("sla_results", "threshold_source")
    op.drop_column("sla_results", "policy_version")
