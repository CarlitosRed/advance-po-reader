"""Explicit isolated database preparation. No schema writes at app startup."""
import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from backend.config import ROOT, Settings

TEST_DATABASES = ("gate_a_test_backend_api", "gate_a_test_backend_catalog", "gate_a_test_backend_contract",
                  "gate_a_test_backend_root", "gate_a_test_backend_gate_a")


def create_database(database_url):
    # Settings enforces loopback and isolated name before this helper can run.
    validated = Settings(_env_file=None, database_url=database_url)
    url = make_url(validated.database_url.get_secret_value())
    name = url.database
    admin = url.set(drivername="postgresql", database="postgres")
    with psycopg.connect(admin.render_as_string(hide_password=False), autocommit=True) as connection:
        if not connection.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,)).fetchone():
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true", help="Create the configured isolated database if absent")
    parser.add_argument("--migrate", action="store_true", help="Explicitly upgrade configured backend database")
    parser.add_argument("--create-test-databases", action="store_true", help="Create separate synthetic test databases")
    args = parser.parse_args()
    if not any(vars(args).values()):
        parser.error("choose --create, --migrate or --create-test-databases")
    settings = Settings()
    if args.create:
        print("Isolated database ready:", create_database(settings.database_url))
    if args.create_test_databases:
        base = make_url(settings.database_url.get_secret_value())
        for name in TEST_DATABASES:
            print("Isolated test database ready:", create_database(base.set(database=name).render_as_string(hide_password=False)))
    if args.migrate:
        command.upgrade(Config(str(ROOT / "backend.alembic.ini")), "head")
        print("Backend migration complete")


if __name__ == "__main__":
    main()
