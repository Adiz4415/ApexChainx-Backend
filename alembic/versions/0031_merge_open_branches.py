"""merge independent migration branches

0026_jobs_json_columns, 0026b/0026c and 0029_sla_config_publish_state /
0030_webhook_soft_delete all branched from 0025_merge_branches and were merged
to main independently, leaving four heads: ``alembic upgrade head`` failed with
"Multiple head revisions are present" and tests/verify_migrations.ts reported a
branched chain. This no-op merge restores a single head so new migrations
(e.g. 0032_snapshot_policy_version) can be applied.

Revision ID: 0031_merge_open_branches
Revises: 0026_jobs_json_columns, 0026c_sla_payment_amounts_bigint, 0029_sla_config_publish_state, 0030_webhook_soft_delete
Create Date: 2026-09-26

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "0031_merge_open_branches"
down_revision: Union[str, None] = (
    "0026_jobs_json_columns",
    "0026c_sla_payment_amounts_bigint",
    "0029_sla_config_publish_state",
    "0030_webhook_soft_delete",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
