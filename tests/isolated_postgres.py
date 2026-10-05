"""Test-owned databases on a private native cluster or an ephemeral CI service."""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@contextmanager
def owned_postgres(scratch, root):
    assert scratch.resolve().is_relative_to(root.resolve()), "runtime must stay inside this desk"
    service = os.environ.get("CI_TEST_POSTGRES_URL")
    if service:
        url = make_url(service)
        if (os.environ.get("GITHUB_ACTIONS") != "true" or
                url.drivername != "postgresql+psycopg" or
                url.host not in {"127.0.0.1", "localhost", "::1"} or
                url.database != "gate_a_test_backend_ci_admin" or url.query):
            raise ValueError("CI service must be an explicit ephemeral loopback test administrator")
        yield url
        return
    suffix = ".exe" if os.name == "nt" else ""
    directory = os.environ.get("GOAL_POSTGRES_BIN")
    initdb = str(Path(directory) / f"initdb{suffix}") if directory else shutil.which("initdb")
    if not initdb or not Path(initdb).is_file():
        raise FileNotFoundError("set GOAL_POSTGRES_BIN to PostgreSQL binaries; no existing database is used")
    pg_ctl = Path(initdb).parent / f"pg_ctl{suffix}"
    cluster = scratch / "cluster"
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

    def run(arguments):
        # A real log file avoids inherited Windows pipe handles keeping a call alive.
        with (scratch / "commands.log").open("a", encoding="utf-8") as log:
            subprocess.run([str(a) for a in arguments], check=True, stdout=log,
                           stderr=subprocess.STDOUT, timeout=60, **flags)

    run([initdb, "-D", cluster, "-U", "goal_tests", "--auth=trust", "--encoding=UTF8", "--locale=C"])
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    run([pg_ctl, "-D", cluster, "-l", scratch / "postgres.log", "-o",
         f"-h 127.0.0.1 -p {port} -c fsync=off", "-w", "start"])
    try:
        yield make_url(f"postgresql+psycopg://goal_tests@127.0.0.1:{port}/postgres")
    finally:
        run([pg_ctl, "-D", cluster, "-m", "fast", "-w", "stop"])


@contextmanager
def owned_database(admin_url, name=None):
    name = name or "gate_a_test_backend_" + uuid4().hex
    if not re.fullmatch(r"gate_a_test_backend_[a-z0-9_]+", name):
        raise ValueError("database must have an explicit isolated-test name")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
    engine = None
    try:
        # CREATE must succeed; never reuse or remove a preexisting database.
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        try:
            engine = create_engine(admin_url.set(database=name), connect_args={"connect_timeout": 3})
            yield engine
        finally:
            if engine is not None:
                engine.dispose()
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{name}"'))
    finally:
        admin.dispose()
