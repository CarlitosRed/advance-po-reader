"""The test-database guard must reject any URL that could reach another database.

Pure URL parsing: no connection is ever opened and no database is touched.
"""
from pathlib import Path
import re

import pytest

from tests.isolated_postgres import require_test_database_url

GOOD = "postgresql+psycopg://user:pw@127.0.0.1:5432/gate_a_test_backend_website"
REJECTED = [
    # Review R02 counterexamples: SQLAlchemy/libpq query overrides.
    GOOD + "?host=example.invalid",
    GOOD + "?dbname=gate_a_backend_website",
    GOOD + "?dbname=other&host=example.invalid&port=1",
    GOOD + "?options=-csearch_path%3Dpublic",
    GOOD + "?service=prod",
    # Driver, host and name boundaries.
    GOOD.replace("postgresql+psycopg", "postgresql"),
    GOOD.replace("postgresql+psycopg", "postgresql+psycopg2"),
    GOOD.replace("127.0.0.1", "example.invalid"),
    GOOD.replace("127.0.0.1", "127.0.0.1,example.invalid"),
    GOOD.replace("127.0.0.1", "10.0.0.5"),
    "postgresql+psycopg://user@/gate_a_test_backend_website",
    GOOD.replace("gate_a_test_backend_website", "gate_a_backend_website"),
    GOOD.replace("gate_a_test_backend_website", "orderlens_product_rows"),
    GOOD.replace("gate_a_test_backend_website", "gate_a_test_backend_"),
    GOOD.replace("gate_a_test_backend_website", "gate_a_test_backend_x%3Fhost%3Dz"),
    GOOD.replace("gate_a_test_backend_website", "gate_a_test_backend_Upper"),
    "postgresql+psycopg://user@127.0.0.1/",
    "not a url",
    "",
]


@pytest.mark.parametrize("value", REJECTED)
def test_unsafe_test_database_urls_are_rejected(value):
    with pytest.raises(ValueError):
        require_test_database_url(value)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_loopback_psycopg_gate_database_is_accepted(host):
    url = require_test_database_url(GOOD.replace("127.0.0.1", host))
    assert url.database == "gate_a_test_backend_website"


def test_exact_name_allow_list_is_enforced():
    allowed = {"gate_a_test_backend_all_products"}
    require_test_database_url(GOOD.replace("website", "all_products"), names=allowed)
    with pytest.raises(ValueError):
        require_test_database_url(GOOD, names=allowed)


def test_every_test_database_fixture_uses_the_shared_guard():
    """Class sweep: no test file may hand-roll its own make_url guard."""
    tests = Path(__file__).resolve().parents[1]
    offenders = []
    for path in tests.rglob("*.py"):
        if path.name in {"isolated_postgres.py", "conftest.py", Path(__file__).name} or path.parts[-2] == "gate_a":
            continue
        source = path.read_text(encoding="utf-8")
        if re.search(r"_TEST_DATABASE_URL|make_url\(", source) and "require_test_database_url" not in source:
            offenders.append(str(path.relative_to(tests)))
    assert not offenders, offenders
