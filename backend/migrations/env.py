"""Alembic environment configuration"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models so autogenerate sees them. Importing the package runs
# app/models/__init__.py, which registers every model with Base.metadata —
# this stays correct as new models are added without editing this file.
from app.models.base import Base  # noqa: F401, E402
import app.models  # noqa: F401, E402

target_metadata = Base.metadata


def _get_url() -> str:
    """Resolve DATABASE_URL from app settings (falls back to alembic.ini value)."""
    try:
        from app.config import settings

        return settings.database_url
    except Exception:
        return config.get_main_option("sqlalchemy.url")


def _include_name(name, type_, parent_names):
    """Limit autogenerate to the schemas this application owns."""
    if type_ == "schema":
        return name in (None, "public", "perf")
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Performance tables live in the perf schema; without this
            # autogenerate neither sees them nor compares them.
            include_schemas=True,
            include_name=_include_name,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
