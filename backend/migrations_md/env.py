"""Alembic environment for market data: ``alembic -n md ...``.

Its own history, apart from the app's, so ``md`` can run on a database of its
own. The version table lives inside the schema, so a dump of ``md`` carries it.
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from app.md.base import MdBase  # noqa: E402
import app.md.models  # noqa: F401, E402

SCHEMA = "md"
# Market data's own metadata: only its tables, so nothing else is compared.
target_metadata = MdBase.metadata


def _get_url() -> str:
    from app.md.config import settings

    return settings.url


def _include_name(name, type_, parent_names):
    if type_ == "schema":
        return name == SCHEMA
    return True


def _include_object(obj, name, type_, reflected, compare_to):
    return not (type_ == "table" and obj.schema != SCHEMA)


def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=SCHEMA,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # The version table needs the schema before the first migration runs.
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=_include_name,
            include_object=_include_object,
            version_table_schema=SCHEMA,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
