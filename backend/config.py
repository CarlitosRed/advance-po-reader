"""Local-only configuration; merely possessing a key never enables requests."""
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PO_BACKEND_", env_file=ROOT / ".env.backend",
                                     extra="forbid", frozen=True, hide_input_in_errors=True)
    host: Literal["127.0.0.1", "localhost", "::1"] = "127.0.0.1"
    port: int = Field(default=8014, ge=1024, le=65535)
    database_url: SecretStr = SecretStr("postgresql+psycopg://gate_a:gate_a_local@127.0.0.1:55433/gate_a_backend_website")
    local_api_token: SecretStr = SecretStr("local-backend-dev-only")
    storage_directory: Path = ROOT / "data" / "backend" / "uploads"
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)
    max_pages: int = Field(default=20, ge=1, le=50)
    max_image_dimension: int = Field(default=8000, ge=100, le=12000)
    max_image_pixels: int = Field(default=25_000_000, ge=10000, le=50_000_000)
    validation_timeout_seconds: int = Field(default=15, ge=1, le=30)
    candidate_limit: int = Field(default=5, ge=1, le=10)
    live_processing_enabled: bool = False
    safety_net_finish_blocking: bool = False
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    extraction_model: str = Field(default="gpt-6-luna", min_length=1, max_length=120)
    provider_store: bool = False
    provider_timeout_seconds: int = Field(default=60, ge=1, le=180)

    @field_validator("database_url")
    @classmethod
    def isolated_database(cls, value):
        try:
            url = make_url(value.get_secret_value())
            valid = (url.drivername == "postgresql+psycopg" and url.host in {"127.0.0.1", "::1", "localhost"}
                     and url.database and url.database.startswith(("gate_a_backend_", "gate_a_test_backend_", "orderlens_product_rows"))
                     and not url.query)
        except Exception:
            valid = False
        if not valid:
            raise ValueError("use a loopback PostgreSQL gate_a_backend_ or gate_a_test_backend_ database")
        return value

    @field_validator("local_api_token")
    @classmethod
    def token_length(cls, value):
        if len(value.get_secret_value()) < 16:
            raise ValueError("local API token requires at least 16 characters")
        return value

    @field_validator("storage_directory")
    @classmethod
    def storage_stays_private(cls, value):
        path = Path(value).resolve()
        if not path.is_relative_to((ROOT / "data").resolve()):
            raise ValueError("storage must stay inside this worktree's ignored data directory")
        return path
