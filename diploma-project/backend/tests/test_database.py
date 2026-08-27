"""Tests for async database infrastructure."""

import asyncio
from unittest.mock import Mock, patch

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import Settings
from app.database import create_database_engine, create_session_factory


def test_create_database_engine_uses_bounded_pool_settings() -> None:
    """The engine factory applies all configured connection limits."""
    settings = Settings(
        _env_file=None,
        database_url=(
            "postgresql+asyncpg://service:secret@database:5432/platform"
        ),
        database_pool_size=8,
        database_max_overflow=4,
        database_pool_timeout_seconds=15,
        database_pool_recycle_seconds=900,
    )
    engine = Mock(spec=AsyncEngine)

    with patch(
        "app.database.create_async_engine",
        return_value=engine,
    ) as create_engine:
        result = create_database_engine(settings)

    assert result is engine
    create_engine.assert_called_once_with(
        str(settings.database_url),
        pool_size=8,
        max_overflow=4,
        pool_timeout=15.0,
        pool_recycle=900,
        pool_pre_ping=True,
        pool_use_lifo=True,
    )


def test_create_session_factory_uses_transaction_safe_defaults() -> None:
    """Sessions retain loaded state after commit and avoid implicit flushes."""
    engine = create_database_engine(Settings(_env_file=None))
    session_factory = create_session_factory(engine)
    session = session_factory()

    try:
        assert isinstance(session, AsyncSession)
        assert session.sync_session.autoflush is False
        assert session.sync_session.expire_on_commit is False
    finally:
        asyncio.run(session.close())
        asyncio.run(engine.dispose())
