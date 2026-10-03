"""Credential-free local configuration. No model/provider configuration exists here."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://gate_a:gate_a_local@127.0.0.1:55432/gate_a"
)


class Settings(BaseSettings):
    """Only loopback application/database endpoints are supported by this gate."""

    model_config = SettingsConfigDict(
        env_prefix="PO_READER_",
        env_file=PROJECT_ROOT / ".env.gate-a",
        env_file_encoding="utf-8",
        extra="forbid",
        hide_input_in_errors=True,
        frozen=True,
    )

    environment: Literal["local"] = "local"
    host: Literal["127.0.0.1", "::1", "localhost"] = "127.0.0.1"
    port: int = Field(default=8000, ge=1024, le=65535)
    database_url: SecretStr = SecretStr(DEFAULT_DATABASE_URL)
    db_connect_timeout_seconds: int = Field(default=2, ge=1, le=10)

    @field_validator("database_url")
    @classmethod
    def local_postgres_only(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("database_url must be a local PostgreSQL URL") from None
        if (
            url.drivername != "postgresql+psycopg"
            or url.host not in {"127.0.0.1", "::1", "localhost"}
            or not url.database
            or url.query
        ):
            raise ValueError(
                "database_url requires postgresql+psycopg, a loopback host, "
                "a database name, and no query overrides"
            )
        return value
