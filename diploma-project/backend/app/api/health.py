"""Service liveness endpoint."""

from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Response returned when the service process is healthy."""

    status: Literal["ok"]


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Check service liveness",
)
async def health_check() -> HealthResponse:
    """Report that the API process is running."""
    return HealthResponse(status="ok")
