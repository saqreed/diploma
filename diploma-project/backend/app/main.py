"""ASGI application entry point."""

from fastapi import FastAPI

from app.api.health import router as health_router


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    application = FastAPI(
        title="Three-Factor Authentication API",
        description=(
            "Backend API for password, TOTP, and continuous behavioral "
            "authentication."
        ),
        version="0.1.0",
    )
    application.include_router(health_router)

    return application


app = create_app()
