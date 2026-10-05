"""ASGI application entry point."""

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.config import Settings, get_settings
from app.api.antifraud import router as antifraud_router
from app.decisions import DomainError
from app.rules import RuleError


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application."""
    application_settings = get_settings() if settings is None else settings
    application = FastAPI(
        title=application_settings.app_name,
        description=(
            "Настраиваемые правила антифрода, решения, журнал и учебное демо."
        ),
        version=application_settings.app_version,
        debug=application_settings.debug,
    )
    application.include_router(health_router)
    application.include_router(antifraud_router)

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        try:
            result = await call_next(request)
        except Exception as error:
            # Do not log raw driver errors, request bodies or secret connection values.
            logging.getLogger("antifraud").error("request_failed request_id=%s path=%s stage=%s error_type=%s", request.state.request_id, request.url.path, getattr(request.state, "stage", "http_adapter"), type(error).__name__)
            result = JSONResponse(status_code=503, content={"code": "service_error", "message": "Не удалось обработать запрос. Действие не разрешено", "request_id": request.state.request_id})
        result.headers["X-Request-ID"] = request.state.request_id
        result.headers["Cache-Control"] = "no-store"
        return result

    @application.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse(status_code=error.status, content={"code": error.code, "message": error.message, "request_id": request.state.request_id})

    @application.exception_handler(RuleError)
    async def settings_error(request, error):
        return JSONResponse(status_code=422, content={"code": "invalid_settings", "message": str(error), "request_id": request.state.request_id})

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse(status_code=422, content={"code": "invalid_request", "message": "Проверьте заполнение обязательных полей", "fields": [".".join(str(p) for p in item["loc"]) for item in error.errors()], "request_id": request.state.request_id})

    return application


app = create_app()
