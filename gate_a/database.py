"""Local database construction and read-only migration readiness checks."""

from typing import Literal

from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.exc import SQLAlchemyError

EXPECTED_REVISION = "0001_gate_a"
DatabaseStatus = Literal["ready", "unavailable", "migration_required"]


def create_db_engine(
    database_url: str | URL, connect_timeout_seconds: int = 2
) -> Engine:
    """Construct a lazy PostgreSQL engine without connecting or changing schema.

    Bounded pool, connection, and statement waits keep an unavailable or locked
    local database from consuming every service worker. SQL parameters are hidden
    from error logs.
    """
    if connect_timeout_seconds < 1:
        raise ValueError("Database connection timeout must be at least one second.")
    url = make_url(database_url)
    if url.drivername != "postgresql+psycopg":
        raise ValueError("Gate A requires the synchronous PostgreSQL psycopg driver.")
    return create_engine(
        url,
        connect_args={
            "connect_timeout": connect_timeout_seconds,
            "options": f"-c statement_timeout={connect_timeout_seconds * 1000}",
        },
        pool_size=2,
        max_overflow=0,
        pool_timeout=connect_timeout_seconds,
        pool_pre_ping=True,
        hide_parameters=True,
    )


def probe_database(engine: Engine) -> DatabaseStatus:
    """Check connectivity and the exact Alembic head, with no migration writes.

    A reachable empty, older, newer, or multi-head database is not ready for this
    application revision. Exceptions never become response bodies or logs here.
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            heads = MigrationContext.configure(connection).get_current_heads()
            if heads != (EXPECTED_REVISION,):
                return "migration_required"
    except SQLAlchemyError:
        return "unavailable"
    return "ready"
