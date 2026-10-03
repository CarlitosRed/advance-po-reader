"""Configuration must keep this foundation local and independent of providers."""

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from gate_a.config import DEFAULT_DATABASE_URL, Settings


def test_defaults_require_no_environment_or_credentials():
    with patch.dict("os.environ", {}, clear=True):
        settings = Settings(_env_file=None)
    assert settings.environment == "local"
    assert settings.database_url.get_secret_value() == DEFAULT_DATABASE_URL
    assert settings.host == "127.0.0.1"


def test_namespaced_environment_overrides_and_provider_keys_are_ignored():
    with patch.dict("os.environ", {
        "PO_READER_PORT": "8123", "OPENAI_API_KEY": "synthetic-unused-key",
        "DATABASE_URL": "postgresql://ignored.invalid/private",
    }, clear=True):
        settings = Settings(_env_file=None)
    assert settings.port == 8123
    assert settings.database_url.get_secret_value() == DEFAULT_DATABASE_URL
    assert "OPENAI_API_KEY" not in Settings.model_fields


def test_explicit_settings_override_environment():
    with patch.dict("os.environ", {"PO_READER_PORT": "8123"}, clear=True):
        assert Settings(port=8001, _env_file=None).port == 8001


def test_dotenv_is_optional_and_environment_takes_precedence(tmp_path):
    dotenv = tmp_path / "synthetic.env"
    dotenv.write_text("PO_READER_PORT=8123\n", encoding="utf-8")
    with patch.dict("os.environ", {"PO_READER_PORT": "8124"}, clear=True):
        assert Settings(_env_file=dotenv).port == 8124
    with patch.dict("os.environ", {}, clear=True):
        assert Settings(_env_file=dotenv).port == 8123


@pytest.mark.parametrize("overrides", [
    {"environment": "production"}, {"host": "0.0.0.0"},
    {"port": 0}, {"port": 65536}, {"db_connect_timeout_seconds": 0},
    {"database_url": "sqlite:///private.sqlite"},
    {"database_url": "postgresql+psycopg://u:p@remote.invalid/gate_a"},
    {"database_url": "postgresql+psycopg://u:p@127.0.0.1/gate_a?host=remote.invalid"},
    {"database_url": "postgresql+psycopg://u:p@127.0.0.1/gate_a?hostaddr=192.0.2.1"},
    {"database_url": "postgresql+psycopg:///gate_a"},
    {"database_url": "not-a-url"},
])
def test_invalid_or_nonlocal_configuration_fails(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_secret_not_exposed_by_repr_or_validation_error():
    secret = "synthetic-credential-check"
    settings = Settings(
        database_url=f"postgresql+psycopg://u:{secret}@127.0.0.1/gate_a", _env_file=None
    )
    assert secret not in repr(settings)
    with pytest.raises(ValidationError) as error:
        Settings(database_url=f"postgresql+psycopg://u:{secret}@remote.invalid/gate_a",
                 _env_file=None)
    assert secret not in str(error.value)
