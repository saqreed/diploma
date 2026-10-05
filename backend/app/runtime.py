"""Lazy runtime engines with independent database principals."""
import os
from functools import cache

from app.config import Settings
from app.database import create_database_engine, create_session_factory


@cache
def antifraud_sessions():
    return create_session_factory(create_database_engine())


@cache
def demo_sessions():
    settings = Settings(_env_file=None, database_url=os.environ["DIPLOMA_DEMO_DATABASE_URL"])
    return create_session_factory(create_database_engine(settings))
