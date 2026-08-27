"""Typed application configuration loaded from the environment."""

from enum import StrEnum
from functools import cache

from pydantic import Field
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


@cache
def get_settings() -> Settings:
    """Load and cache process-wide application settings."""
    return Settings()
