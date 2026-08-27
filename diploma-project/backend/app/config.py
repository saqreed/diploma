"""Typed application configuration loaded from the environment."""

from enum import StrEnum
from functools import cache

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Supported application runtime environments."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Application settings loaded from ``DIPLOMA_*`` variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DIPLOMA_",
        extra="ignore",
        frozen=True,
    )

    app_name: str = Field(
        default="Three-Factor Authentication API",
        min_length=1,
    )
    app_version: str = Field(default="0.1.0", min_length=1)
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    database_url: PostgresDsn = PostgresDsn(
        "postgresql+asyncpg://diploma:diploma@localhost:5432/diploma"
    )
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=5, ge=0, le=20)
    database_pool_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60, le=3600)


@cache
def get_settings() -> Settings:
    """Load and cache process-wide application settings."""
    return Settings()
