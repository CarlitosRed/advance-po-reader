"""Offline backend checks with opt-in, test-owned PostgreSQL provisioning."""
import builtins
from contextlib import ExitStack
import io
import os
from pathlib import Path

import httpx
import pytest

from tests.isolated_postgres import owned_database, owned_postgres

ROOT = Path(__file__).resolve().parents[2]
DATABASE_VARIABLES = (
    "PO_BACKEND_TEST_DATABASE_URL", "PO_BACKEND_API_TEST_DATABASE_URL",
    "PO_BACKEND_POOL_TEST_DATABASE_URL", "PO_BACKEND_CONTRACT_TEST_DATABASE_URL",
    "PO_BACKEND_POOL_MIGRATION_TEST_DATABASE_URL",
)


def pytest_addoption(parser):
    parser.addoption("--isolated-backend", action="store_true",
                     help="Provision all backend databases on a private native cluster or ephemeral CI service")


@pytest.fixture(scope="session", autouse=True)
def backend_offline_boundary(request):
    with pytest.MonkeyPatch.context() as patch:
        for name in list(os.environ):
            explicit_test_db = name in DATABASE_VARIABLES and not request.config.getoption("--isolated-backend")
            if not explicit_test_db and (name == "OPENAI_API_KEY" or name.startswith(("PO_BACKEND_", "PG"))):
                patch.delenv(name, raising=False)
        original_open, original_os_open = builtins.open, os.open

        def guard(path):
            if isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)).name.casefold().startswith(".env"):
                raise RuntimeError("backend tests must never open dotenv files")

        def safe_open(path, *args, **kwargs):
            guard(path)
            return original_open(path, *args, **kwargs)

        def safe_os_open(path, *args, **kwargs):
            guard(path)
            return original_os_open(path, *args, **kwargs)

        def forbidden(*args, **kwargs):
            raise RuntimeError("backend tests require injected mocks; real HTTP is forbidden")

        patch.setattr(builtins, "open", safe_open)
        patch.setattr(io, "open", safe_open)
        patch.setattr(os, "open", safe_os_open)
        patch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
        patch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
        yield


@pytest.fixture(scope="session", autouse=True)
def isolated_backend_databases(request, tmp_path_factory, backend_offline_boundary):
    if not request.config.getoption("--isolated-backend"):
        yield
        return
    scratch = tmp_path_factory.mktemp("backend-postgres")
    with ExitStack() as stack:
        admin_url = stack.enter_context(owned_postgres(scratch, ROOT))
        patch = stack.enter_context(pytest.MonkeyPatch.context())
        for variable in DATABASE_VARIABLES:
            # The historical migration test requires this exact name and an empty DB.
            name = ("gate_a_test_backend_all_products_migration" if "MIGRATION" in variable else
                    "gate_a_test_backend_all_products" if variable == "PO_BACKEND_POOL_TEST_DATABASE_URL" else None)
            engine = stack.enter_context(owned_database(admin_url, name))
            patch.setenv(variable, engine.url.render_as_string(hide_password=False))
        yield
