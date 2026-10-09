"""Backend migrations are explicit and use a separate local backend database."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import text

from backend.config import Settings
from backend import models  # Register every backend table on Gate A metadata.
from gate_a.database import create_db_engine
from gate_a.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def offline() -> None:
    context.configure(url=Settings().database_url.get_secret_value(),
                      target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def migrate(connection) -> None:
    # Optional extension absence also means these optional indexes are absent;
    # metadata comparison must not propose unsupported index creation.
    has_trgm = bool(connection.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace "
        "WHERE e.extname='pg_trgm' AND n.nspname='public')")))
    optional_indexes = {"ix_products_sku_trgm", "ix_products_description_trgm", "ix_aliases_value_trgm"}

    def include_object(object_, name, type_, reflected, compare_to):
        return not (type_ == "index" and name in optional_indexes and not has_trgm)

    context.configure(connection=connection, target_metadata=target_metadata,
                      compare_type=True, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


def online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        migrate(connection)
        return
    engine = create_db_engine(Settings().database_url.get_secret_value())
    try:
        # The capability read above starts a transaction. Own and commit it here
        # so Alembic does not misclassify it as a caller-owned transaction.
        with engine.begin() as connection:
            migrate(connection)
    finally:
        engine.dispose()


offline() if context.is_offline_mode() else online()
