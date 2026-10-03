"""Synthetic DB tests: SQLite/offline SQL are surrogates, not live PostgreSQL.

Set GATE_A_TEST_DATABASE_URL only for an empty, loopback PostgreSQL test database
whose name starts with gate_a_test_. The migration test rolls back all DDL. The
lock test commits only its own baseline and removes those tables in finally.
"""

from io import StringIO
import os
from pathlib import Path
from time import monotonic
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from gate_a.database import EXPECTED_REVISION, create_db_engine, probe_database
from gate_a.models import DEVELOPMENT_TENANT_ID, DEVELOPMENT_TENANT_NAME, Tenant

ROOT = Path(__file__).resolve().parents[2]


def migration_config(connection=None) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


@pytest.fixture
def sqlite_surrogate(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'synthetic.sqlite3').as_posix()}")
    try:
        yield engine
    finally:
        engine.dispose()


def test_sqlite_surrogate_upgrade_seed_constraints_and_downgrade(sqlite_surrogate):
    engine = sqlite_surrogate
    assert probe_database(engine) == "migration_required"
    assert inspect(engine).get_table_names() == []
    with engine.begin() as connection:
        command.upgrade(migration_config(connection), "head")
    assert set(inspect(engine).get_table_names()) == {"tenants", "alembic_version"}
    assert probe_database(engine) == "ready"
    with Session(engine) as session:
        tenant = session.get(Tenant, DEVELOPMENT_TENANT_ID)
        assert tenant.name == DEVELOPMENT_TENANT_NAME
        assert tenant.created_at is not None
        session.add(Tenant(name="Another synthetic tenant"))
        session.commit()
        assert len(session.scalars(select(Tenant)).all()) == 2
    with engine.begin() as connection:
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                Tenant.__table__.insert(), {"id": DEVELOPMENT_TENANT_ID, "name": "Duplicate"}
            )
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(Tenant.__table__.insert(), {"id": uuid4(), "name": "   "})
    with engine.begin() as connection:
        command.downgrade(migration_config(connection), "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    assert probe_database(engine) == "migration_required"


@pytest.mark.parametrize("heads", [[], ["older_revision"], ["newer_revision"], [EXPECTED_REVISION, "other_head"]])
def test_sqlite_surrogate_readiness_requires_exact_single_head(sqlite_surrogate, heads):
    engine = sqlite_surrogate
    with engine.begin() as connection:
        command.upgrade(migration_config(connection), "head")
        connection.execute(text("DELETE FROM alembic_version"))
        for head in heads:
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:head)"), {"head": head}
            )
    assert probe_database(engine) == "migration_required"
    # A readiness probe must not repair or otherwise mutate the revision state.
    with engine.connect() as connection:
        assert set(connection.scalars(text("SELECT version_num FROM alembic_version"))) == set(heads)


def test_database_probe_reports_unavailable_without_error_details(sqlite_surrogate, monkeypatch):
    def unavailable():
        raise OperationalError("secret SQL", {}, Exception("private connection details"))

    monkeypatch.setattr(sqlite_surrogate, "connect", unavailable)
    assert probe_database(sqlite_surrogate) == "unavailable"


def test_postgres_engine_creation_does_not_connect(monkeypatch):
    import psycopg

    def forbidden(*args, **kwargs):
        raise AssertionError("A lazy engine must connect only when explicitly used.")

    monkeypatch.setattr(psycopg, "connect", forbidden)
    engine = create_db_engine("postgresql+psycopg://synthetic:synthetic@127.0.0.1:55432/gate_a_test_lazy")
    try:
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "psycopg"
        with pytest.raises(AssertionError, match="lazy engine"):
            engine.connect()
    finally:
        engine.dispose()


@pytest.mark.parametrize("database_url", ["sqlite://", "postgresql://synthetic@localhost/synthetic"])
def test_engine_rejects_other_database_drivers(database_url):
    with pytest.raises(ValueError, match="synchronous PostgreSQL psycopg"):
        create_db_engine(database_url)


def test_engine_rejects_unbounded_connection_timeout():
    with pytest.raises(ValueError, match="at least one second"):
        create_db_engine("postgresql+psycopg://synthetic@localhost/synthetic", 0)


def test_offline_migration_generates_postgresql_sql_without_connecting(monkeypatch):
    import psycopg

    def forbidden(*args, **kwargs):
        pytest.fail("Offline migration generation must not connect to a database.")

    monkeypatch.setattr(psycopg, "connect", forbidden)
    config = migration_config()
    config.output_buffer = StringIO()
    command.upgrade(config, "head", sql=True)
    sql = config.output_buffer.getvalue()
    assert "CREATE TABLE tenants" in sql
    assert "id UUID NOT NULL" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "00000000-0000-0000-0000-000000000001" in sql
    assert EXPECTED_REVISION in sql


def isolated_postgresql_test_url():
    database_url = os.environ.get("GATE_A_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("No isolated live PostgreSQL test database configured; surrogate tests are separate.")
    url = make_url(database_url)
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not (url.database or "").startswith("gate_a_test_")
        or url.query
    ):
        pytest.fail("Live tests require a loopback psycopg database named gate_a_test_* with no query overrides.")
    return url


def require_empty_test_database(connection):
    user_relations = connection.execute(text(
        "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema' LIMIT 1"
    )).first()
    if user_relations is not None:
        pytest.fail("Live PostgreSQL test database is not empty; no changes were made.")
    connection.rollback()


@pytest.mark.parametrize("query", ["host=remote.invalid", "dbname=unrelated", "options=-c%20search_path%3Dunrelated"])
def test_live_database_guard_rejects_query_overrides_before_connecting(monkeypatch, query):
    monkeypatch.setenv(
        "GATE_A_TEST_DATABASE_URL",
        f"postgresql+psycopg://synthetic:synthetic@127.0.0.1:5432/gate_a_test_guard?{query}",
    )
    with pytest.raises(pytest.fail.Exception, match="no query overrides"):
        isolated_postgresql_test_url()


@pytest.mark.postgresql
def test_live_postgresql_upgrade_seed_downgrade_in_rolled_back_transaction():
    url = isolated_postgresql_test_url()
    engine = create_db_engine(url)
    try:
        with engine.connect() as connection:
            require_empty_test_database(connection)
            transaction = connection.begin()
            try:
                command.upgrade(migration_config(connection), "head")
                assert set(inspect(connection).get_table_names()) == {"alembic_version", "tenants"}
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == EXPECTED_REVISION
                row = connection.execute(select(Tenant.__table__)).one()
                assert row.id == DEVELOPMENT_TENANT_ID
                assert row.name == DEVELOPMENT_TENANT_NAME
                assert row.created_at.utcoffset() is not None
                assert "UUID" in str(inspect(connection).get_columns("tenants")[0]["type"])
                command.downgrade(migration_config(connection), "base")
                assert inspect(connection).get_table_names() == ["alembic_version"]
            finally:
                transaction.rollback()
        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


@pytest.mark.postgresql
def test_live_postgresql_locked_revision_returns_unavailable_within_statement_timeout():
    url = isolated_postgresql_test_url()
    engine = create_db_engine(url, connect_timeout_seconds=1)
    upgraded = False
    try:
        with engine.connect() as connection:
            require_empty_test_database(connection)
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "head")
        upgraded = True
        assert probe_database(engine) == "ready"
        with engine.connect() as lock_connection:
            with lock_connection.begin():
                assert lock_connection.scalar(text("SHOW statement_timeout")) == "1s"
                lock_connection.execute(text("LOCK TABLE alembic_version IN ACCESS EXCLUSIVE MODE"))
                started = monotonic()
                assert probe_database(engine) == "unavailable"
                elapsed = monotonic() - started
                assert 0.5 <= elapsed < 4, f"The one-second statement timeout took {elapsed:.2f}s"
        # A timed-out read does not corrupt the database or its revision state.
        assert probe_database(engine) == "ready"
    finally:
        try:
            if upgraded:
                # The preflight proved the DB empty; these are this test's tables.
                # This runs after the lock connection's transaction has released.
                with engine.begin() as connection:
                    command.downgrade(migration_config(connection), "base")
                    connection.execute(text("DROP TABLE alembic_version"))
                assert inspect(engine).get_table_names() == []
        finally:
            engine.dispose()
