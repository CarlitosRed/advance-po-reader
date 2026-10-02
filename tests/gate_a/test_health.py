"""Synthetic probes and a real connection-refusal path; no provider or PDF use."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from gate_a.app import create_app
from gate_a.config import Settings
from gate_a.database import EXPECTED_REVISION


def local_settings(**overrides):
    return Settings(_env_file=None, **overrides)


def test_startup_liveness_configuration_schema_make_no_connection():
    engine = create_engine("sqlite://")
    secret = "synthetic-never-exposed"
    settings = local_settings(database_url=f"postgresql+psycopg://u:{secret}@127.0.0.1/gate_a")
    with patch.object(engine, "connect", side_effect=AssertionError("unexpected DB use")):
        with TestClient(create_app(settings, engine=engine)) as client:
            assert client.get("/health/live").json() == {"status": "alive", "gate": "A"}
            configuration = client.get("/configuration")
            assert configuration.status_code == 200
            assert secret not in configuration.text
            assert "database_url" not in configuration.json()
            assert configuration.json()["extraction_payload_finalized"] is False
            schema = client.get("/contracts/product-document/v1/schema")
            assert schema.status_code == 200
            assert schema.json()["properties"]["schema_version"]["const"] == "1.0"
            assert secret not in client.get("/openapi.json").text
    engine.dispose()


@pytest.mark.parametrize("probe_status,http_status", [
    ("ready", 200), ("unavailable", 503), ("migration_required", 503),
])
def test_readiness_status_does_not_change_liveness(probe_status, http_status):
    with patch("gate_a.app.probe_database", return_value=probe_status):
        with TestClient(create_app(local_settings())) as client:
            response = client.get("/health/ready")
            assert response.status_code == http_status
            assert response.json() == {
                "status": "ready" if probe_status == "ready" else "not_ready",
                "database": probe_status,
                "expected_revision": EXPECTED_REVISION,
            }
            assert client.get("/health/live").status_code == 200


def test_database_free_startup_and_unmigrated_database_is_not_ready():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    with TestClient(create_app(local_settings(), engine=engine)) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["database"] == "migration_required"
        assert client.get("/health/live").status_code == 200
    engine.dispose()


def test_route_surface_is_gate_a_get_only():
    app = create_app(local_settings())
    paths = app.openapi()["paths"]
    assert set(paths) == {
        "/health/live", "/health/ready", "/configuration",
        "/contracts/product-document/v1/schema",
    }
    assert all(set(operations) == {"get"} for operations in paths.values())


def test_owned_engine_disposed_on_shutdown():
    engine = create_engine("sqlite://")
    with patch("gate_a.app.create_db_engine", return_value=engine):
        with patch.object(engine, "dispose", wraps=engine.dispose) as dispose:
            with TestClient(create_app(local_settings())) as client:
                assert client.get("/health/live").status_code == 200
                dispose.assert_not_called()
            dispose.assert_called_once()
