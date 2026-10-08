"""Tests for FastAPI application foundation, health endpoint, and error handling."""

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.api.v1.router import api_router
from app.core.config import settings
from app.main import app, unhandled_exception_handler


@pytest.fixture
def client() -> TestClient:
    """Fixture providing a test client for the production FastAPI application."""
    return TestClient(app, raise_server_exceptions=False)


def test_health_check_returns_200(client: TestClient):
    """Verify that GET /health returns HTTP 200 and expected status payload."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_v1_router_is_mounted():
    """Verify that the /api/v1 routing foundation is mounted in the application."""
    assert settings.API_V1_PREFIX == "/api/v1"

    # Verify that api_router is registered within app routes with prefix /api/v1
    matching_routes = [
        route
        for route in app.routes
        if (
            hasattr(route, "include_context")
            and getattr(route.include_context, "prefix", None) == settings.API_V1_PREFIX
        )
        or getattr(route, "path", "").startswith(settings.API_V1_PREFIX)
    ]
    assert len(matching_routes) > 0


def test_api_v1_routing_dispatches_with_prefix():
    """Verify that a router included with API_V1_PREFIX dispatches prefixed routes correctly."""
    test_app = FastAPI()
    test_app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    local_router = APIRouter()

    @local_router.get("/probe")
    def _probe():
        return {"probe": "v1-mounted"}

    test_app.include_router(local_router, prefix=settings.API_V1_PREFIX)
    test_client = TestClient(test_app)

    response = test_client.get(f"{settings.API_V1_PREFIX}/probe")
    assert response.status_code == 200
    assert response.json() == {"probe": "v1-mounted"}


def test_http_404_error_handling(client: TestClient):
    """Verify that standard HTTP exceptions return predictable details."""
    response = client.get("/nonexistent-endpoint")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_unhandled_exception_returns_500():
    """Verify that unexpected exceptions return 500 without leaking internal details."""
    test_app = FastAPI()
    test_app.add_exception_handler(Exception, unhandled_exception_handler)

    @test_app.get("/_test_unhandled_error")
    def _error_route():
        raise RuntimeError("Unexpected internal crash")

    test_client = TestClient(test_app, raise_server_exceptions=False)
    response = test_client.get("/_test_unhandled_error")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
