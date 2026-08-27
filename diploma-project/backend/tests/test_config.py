"""Tests for typed application configuration."""

import pytest
from pydantic import ValidationError

from app.config import Environment, Settings, get_settings
from app.main import create_app

SETTINGS_ENVIRONMENT_VARIABLES = (
    "DIPLOMA_APP_NAME",
    "DIPLOMA_APP_VERSION",
    "DIPLOMA_ENVIRONMENT",
    "DIPLOMA_DEBUG",
    "DIPLOMA_DATABASE_URL",
    "DIPLOMA_DATABASE_POOL_SIZE",
    "DIPLOMA_DATABASE_MAX_OVERFLOW",
    "DIPLOMA_DATABASE_POOL_TIMEOUT_SECONDS",
    "DIPLOMA_DATABASE_POOL_RECYCLE_SECONDS",
)


@pytest.fixture(autouse=True)
def isolate_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep configuration tests independent from the host environment."""
    for variable_name in SETTINGS_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable_name, raising=False)


def test_settings_use_safe_defaults() -> None:
    """The backend starts with deterministic non-production defaults."""
    settings = Settings(_env_file=None)

    assert settings.app_name == "Three-Factor Authentication API"
    assert settings.app_version == "0.1.0"
    assert settings.environment is Environment.DEVELOPMENT
    assert settings.debug is False
    assert settings.database_url.hosts()[0]["host"] == "localhost"
    assert settings.database_url.path == "/diploma"
    assert settings.database_pool_size == 5
    assert settings.database_max_overflow == 5
    assert settings.database_pool_timeout_seconds == 30.0
    assert settings.database_pool_recycle_seconds == 1800


def test_settings_load_prefixed_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the documented prefixed variables configure the process."""
    monkeypatch.setenv("DIPLOMA_APP_NAME", "Configured API")
    monkeypatch.setenv("DIPLOMA_APP_VERSION", "1.2.3")
    monkeypatch.setenv("DIPLOMA_ENVIRONMENT", "testing")
    monkeypatch.setenv("DIPLOMA_DEBUG", "true")

    settings = Settings(_env_file=None)

    assert settings.app_name == "Configured API"
    assert settings.app_version == "1.2.3"
    assert settings.environment is Environment.TESTING
    assert settings.debug is True


def test_settings_load_database_pool_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Database connection limits are configurable within validated bounds."""
    monkeypatch.setenv(
        "DIPLOMA_DATABASE_URL",
        "postgresql+asyncpg://service:secret@database:5432/platform",
    )
    monkeypatch.setenv("DIPLOMA_DATABASE_POOL_SIZE", "8")
    monkeypatch.setenv("DIPLOMA_DATABASE_MAX_OVERFLOW", "4")
    monkeypatch.setenv("DIPLOMA_DATABASE_POOL_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("DIPLOMA_DATABASE_POOL_RECYCLE_SECONDS", "900")

    settings = Settings(_env_file=None)

    assert settings.database_url.hosts()[0]["host"] == "database"
    assert settings.database_url.path == "/platform"
    assert settings.database_pool_size == 8
    assert settings.database_max_overflow == 4
    assert settings.database_pool_timeout_seconds == 15.0
    assert settings.database_pool_recycle_seconds == 900


def test_settings_reject_unknown_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid environment names fail during startup configuration."""
    monkeypatch.setenv("DIPLOMA_ENVIRONMENT", "staging")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_get_settings_caches_process_configuration() -> None:
    """Repeated dependency calls reuse one immutable settings instance."""
    get_settings.cache_clear()

    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


def test_application_factory_uses_injected_settings() -> None:
    """The application factory exposes configuration through FastAPI metadata."""
    settings = Settings(
        _env_file=None,
        app_name="Test API",
        app_version="9.8.7",
        environment=Environment.TESTING,
        debug=True,
    )

    application = create_app(settings)

    assert application.title == "Test API"
    assert application.version == "9.8.7"
    assert application.debug is True
