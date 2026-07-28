"""ASGI application entry point."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    return FastAPI(
        title="Three-Factor Authentication API",
        description=(
            "Backend API for password, TOTP, and continuous behavioral "
            "authentication."
        ),
        version="0.1.0",
    )


app = create_app()
