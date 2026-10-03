"""Read only the loopback connection settings, never a provider credential."""
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class ConnectionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PO_BACKEND_", env_file=ROOT / ".env.backend",
        extra="ignore", frozen=True, hide_input_in_errors=True)
    host: Literal["127.0.0.1", "localhost", "::1"] = "127.0.0.1"
    port: int = Field(default=8014, ge=1024, le=65535)
    local_api_token: SecretStr = SecretStr("local-backend-dev-only")

    @field_validator("local_api_token")
    @classmethod
    def token_length(cls, value):
        if len(value.get_secret_value()) < 16:
            raise ValueError("local connection token requires at least 16 characters")
        return value

    @property
    def base_url(self):
        host = "[::1]" if self.host == "::1" else self.host
        return f"http://{host}:{self.port}"
