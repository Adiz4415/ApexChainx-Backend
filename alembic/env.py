from logging.config import fileConfig

from sqlalchemy import String, engine_from_config, inspect, pool, text

import app.models.job
import app.models.orm.outage
import app.models.orm.outage_event
import app.models.orm.payment
import app.models.orm.sla
import app.models.sla_dispute
import app.models.webhook  # noqa: F401
from alembic import context
from app.core.config import settings

# Import all ORM models so Alembic can detect them
from app.db.base import Base
import app.models.orm.audit_log  # noqa: F401
import app.models.orm.outage  # noqa: F401
import app.models.orm.outage_event  # noqa: F401
import app.models.orm.sla  # noqa: F401
import app.models.orm.payment  # noqa: F401
import app.models.job  # noqa: F401
import app.models.webhook  # noqa: F401
import app.models.sla_dispute  # noqa: F401


config = context.config

# Override sqlalchemy.url with value from app settings
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# Alembic 1.14 hardcodes ``alembic_version.version_num`` as VARCHAR(32) when it
# creates the bookkeeping table (alembic/ddl/impl.py ``version_table_impl`` has
# no length override in this release). This repo's descriptive revision ids run
# to 47 chars ("0029_sla_config_publish_state"), so on any fresh database the
# upgrade chain dies with StringDataRightTruncation the first time a long id is
# stamped. Pre-create / widen the table before Alembic touches it.
ALEMBIC_VERSION_NUM_LENGTH = 255


def _ensure_wide_version_table(connection) -> None:
    """Create or widen ``alembic_version.version_num`` for long revision ids."""
    inspector = inspect(connection)
    if not inspector.has_table("alembic_version"):
        connection.execute(
            text(
                "CREATE TABLE alembic_version ("
                "version_num VARCHAR(255) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )
        connection.commit()
        return

    columns = inspector.get_columns("alembic_version")
    version_col = next((c for c in columns if c["name"] == "version_num"), None)
    if (
        version_col is not None
        and isinstance(version_col["type"], String)
        and (version_col["type"].length or 0) < ALEMBIC_VERSION_NUM_LENGTH
    ):
        connection.execute(text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)"))
        connection.commit()
        return

    # Nothing needed changing. inspect() ran read queries, which autobegins a
    # transaction on the shared connection; close it so Alembic's
    # transaction_per_migration bookkeeping starts from a clean connection.
    connection.rollback()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _ensure_wide_version_table(connection)
        # Migrations 0023/0024 use autocommit_block() for CREATE INDEX
        # CONCURRENTLY. With a single run-wide transaction, the first
        # autocommit block commits it out from under Alembic and any later
        # block raises an assertion. transaction_per_migration is the setup
        # Alembic's own docs require when migrations contain autocommit blocks.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
