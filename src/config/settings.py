from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # AWS
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    s3_bucket_name: str = "bevar-ukraine-emails-archive-andriy-kuzmyn"
    s3_object_key: str = "bevar-ukraine-mails.mbox"

    # Bedrock LLM
    bedrock_model_id: str = "us.anthropic.claude-sonnet-4-6"

    # Database
    duckdb_path: str = "data/emails.duckdb"

    # App
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # Security
    secret_key: str = "change-me-in-production"
    allowed_origins: str = "http://localhost:8000"

    # Pagination defaults
    default_page_size: int = Field(default=50, ge=1, le=500)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def duckdb_full_path(self) -> Path:
        p = Path(self.duckdb_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
