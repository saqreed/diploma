"""Async SQLAlchemy engine and session factories."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings


def create_database_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create a lazy, pooled PostgreSQL engine without opening a connection."""
    database_settings = get_settings() if settings is None else settings

    return create_async_engine(
        str(database_settings.database_url),
        pool_size=database_settings.database_pool_size,
        max_overflow=database_settings.database_max_overflow,
        pool_timeout=database_settings.database_pool_timeout_seconds,
        pool_recycle=database_settings.database_pool_recycle_seconds,
        pool_pre_ping=True,
        pool_use_lifo=True,
    )


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create the unit-of-work session factory bound to an async engine."""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )
