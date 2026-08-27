"""ASGI application entry point."""

from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application."""
    application_settings = get_settings() if settings is None else settings
    application = FastAPI(
        title=application_settings.app_name,
        description=(
            "Backend API for password, TOTP, and continuous behavioral "
            "authentication."
        ),
        version=application_settings.app_version,
        debug=application_settings.debug,
    )
    application.include_router(health_router)

    return application


app = create_app()
