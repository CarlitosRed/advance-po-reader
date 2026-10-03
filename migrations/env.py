"""Explicit Alembic entry point; the application never invokes it on startup."""

from logging.config import fileConfig

from alembic import context

from gate_a.config import Settings
from gate_a.database import create_db_engine
from gate_a.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=Settings().database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def migrate_connection(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Tests and trusted local tooling may supply their own isolated connection.
    # Do not construct/read a configured database when a connection is provided.
    connection = config.attributes.get("connection")
    if connection is not None:
        migrate_connection(connection)
        return
    engine = create_db_engine(Settings().database_url.get_secret_value())
    try:
        with engine.connect() as connection:
            migrate_connection(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
