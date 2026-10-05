"""Smoke tests for the service liveness endpoint."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_check_reports_service_is_running() -> None:
    """The liveness endpoint responds with its stable public contract."""
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"status": "ok"}
