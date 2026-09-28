import pytest
from alembic.command import downgrade, upgrade
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import settings


def _schema_drift() -> list[str]:
    """Diff ORM metadata against the migrated schema (empty list = parity)."""
    import sqlalchemy as sa

    from app.db.base import Base
    from app.db.session import engine

    # Import every ORM module so all tables register on Base.metadata
    import app.models.job  # noqa: F401
    import app.models.orm.api_key  # noqa: F401
    import app.models.orm.audit_log  # noqa: F401
    import app.models.orm.outage  # noqa: F401
    import app.models.orm.outage_event  # noqa: F401
    import app.models.orm.payment  # noqa: F401
    import app.models.orm.session  # noqa: F401
    import app.models.orm.sla  # noqa: F401
    import app.models.orm.sla_config_history  # noqa: F401
    import app.models.orm.sla_snapshot  # noqa: F401
    import app.models.orm.token_family  # noqa: F401
    import app.models.orm.user  # noqa: F401
    import app.models.webhook  # noqa: F401
    import app.models.sla_dispute  # noqa: F401

    insp = sa.inspect(engine)
    db_tables = set(insp.get_table_names())
    drift: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in db_tables:
            drift.append(f"table missing in DB: {table_name}")
            continue
        db_cols = {c["name"] for c in insp.get_columns(table_name)}
        for col in table.columns:
            if col.name not in db_cols:
                drift.append(f"{table_name}.{col.name} in ORM, missing in DB")
    return drift


@pytest.mark.skipif(
    "sqlite" in settings.DATABASE_URL,
    reason="Requires PostgreSQL for alembic migrations",
)
class TestMigrationRoundTrip:
    @pytest.fixture(scope="class")
    def alembic_cfg(self):
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
        return cfg

    @pytest.fixture(scope="class")
    def all_revisions(self, alembic_cfg):
        script = ScriptDirectory.from_config(alembic_cfg)
        # Return Revision objects (not bare revision-id strings) so callers
        # can read .revision / .down_revision.
        return list(script.walk_revisions())

    def test_each_migration_upgrade_and_downgrade(self, alembic_cfg):
        script = ScriptDirectory.from_config(alembic_cfg)
        heads = script.get_heads()
        assert len(heads) > 0, "No migration heads found"

    def test_upgrade_head_then_downgrade_base(self, alembic_cfg, all_revisions):
        upgrade(alembic_cfg, "head")
        downgrade(alembic_cfg, "base")

    def test_downgrade_round_trip_per_revision(self, alembic_cfg, all_revisions):
        for rev in all_revisions:
            # Merge revisions carry a tuple of down_revisions, which is not a
            # valid single downgrade target; their children cover the paths.
            if isinstance(rev.down_revision, str):
                upgrade(alembic_cfg, rev.revision)
                downgrade(alembic_cfg, rev.down_revision)
                upgrade(alembic_cfg, rev.revision)

    def test_upgrade_from_base_to_head(self, alembic_cfg):
        upgrade(alembic_cfg, "base")
        upgrade(alembic_cfg, "head")

    def test_downgrade_from_head_to_base(self, alembic_cfg):
        upgrade(alembic_cfg, "head")
        downgrade(alembic_cfg, "base")

    def test_upgrade_and_downgrade_full_cycle(self, alembic_cfg, all_revisions):
        """Full lifecycle: base -> head -> base -> head.

        Per-revision transitions are covered by
        test_downgrade_round_trip_per_revision; with merged branches, sibling
        revisions are not ancestors of the current head, so stepping through
        every down_revision individually is not a valid downgrade path.
        """
        upgrade(alembic_cfg, "head")
        downgrade(alembic_cfg, "base")
        upgrade(alembic_cfg, "head")
        downgrade(alembic_cfg, "base")
        upgrade(alembic_cfg, "head")

    def test_migrated_schema_matches_orm(self, alembic_cfg):
        """After upgrade head, every ORM column must exist in the database.

        create_all-built test DBs hide drift between the models and the
        migration chain; this catches columns the app uses but no migration
        ever created (the class of outage behind #567's checksum failures).
        """
        upgrade(alembic_cfg, "head")
        drift = _schema_drift()
        assert not drift, f"migration chain diverged from ORM: {drift}"
