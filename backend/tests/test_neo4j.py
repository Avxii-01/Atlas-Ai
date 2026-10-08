"""Automated tests for Neo4j connection layer, session lifecycle, and database health."""

from unittest.mock import MagicMock, patch
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from neo4j import Session

from app.core.config import Settings, settings
from app.db.neo4j import (
    Neo4jConnectionError,
    close_driver,
    get_driver,
    get_neo4j_session,
    init_driver,
    set_driver,
    verify_connectivity,
)
from app.main import app


@pytest.fixture(autouse=True)
def reset_driver_state():
    """Ensure driver state is reset before and after every test."""
    set_driver(None)
    yield
    set_driver(None)


def test_neo4j_configuration_defaults_and_overrides(monkeypatch: pytest.MonkeyPatch):
    """Verify default and overridden Neo4j configuration loading."""
    # Ensure NEO4J_PASSWORD is not set in environment for default check
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)

    # Default settings verification
    default_settings = Settings()
    assert default_settings.NEO4J_URI == "bolt://neo4j:7687"
    assert default_settings.NEO4J_USERNAME == "neo4j"
    assert default_settings.NEO4J_PASSWORD == ""

    # Environment variable override verification
    monkeypatch.setenv("NEO4J_URI", "bolt://testhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "custom_user")
    monkeypatch.setenv("NEO4J_PASSWORD", "custom_secret")

    custom_settings = Settings()
    assert custom_settings.NEO4J_URI == "bolt://testhost:7687"
    assert custom_settings.NEO4J_USERNAME == "custom_user"
    assert custom_settings.NEO4J_PASSWORD == "custom_secret"


def test_driver_creation_uses_configured_uri_and_credentials():
    """Verify driver creation uses configured and custom parameters."""
    with patch("app.db.neo4j.GraphDatabase.driver") as mock_driver_factory:
        mock_driver = MagicMock()
        mock_driver_factory.return_value = mock_driver

        # Call with defaults
        driver = init_driver()
        assert driver is mock_driver
        mock_driver_factory.assert_called_once_with(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
        )

        mock_driver_factory.reset_mock()

        # Call with explicit overrides
        custom_driver = init_driver(
            uri="bolt://other:7687",
            auth=("other_user", "other_pass"),
        )
        assert custom_driver is mock_driver
        mock_driver_factory.assert_called_once_with(
            "bolt://other:7687",
            auth=("other_user", "other_pass"),
        )


def test_driver_lifecycle_behavior():
    """Verify driver initialization, retrieval, closure, and uninitialized error handling."""
    # When uninitialized, get_driver must raise Neo4jConnectionError
    with pytest.raises(Neo4jConnectionError, match="not initialized"):
        get_driver()

    mock_driver = MagicMock()
    with patch("app.db.neo4j.GraphDatabase.driver", return_value=mock_driver):
        init_driver()
        assert get_driver() is mock_driver

        # Closing driver should call driver.close() and clear driver state
        close_driver()
        mock_driver.close.assert_called_once()

        with pytest.raises(Neo4jConnectionError, match="not initialized"):
            get_driver()


def test_fastapi_lifespan_manages_driver_lifecycle():
    """Verify FastAPI application lifespan initializes and closes the driver."""
    with (
        patch("app.main.init_driver") as mock_init,
        patch("app.main.close_driver") as mock_close,
    ):
        mock_driver = MagicMock()
        mock_init.return_value = mock_driver

        with TestClient(app):
            mock_init.assert_called_once()
            assert not mock_close.called

        mock_close.assert_called_once()


def test_session_acquisition_and_safe_closure():
    """Verify session generator acquires a session and closes it safely upon exit."""
    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    session_generator = get_neo4j_session()
    acquired_session = next(session_generator)
    assert acquired_session is mock_session
    assert not mock_session.close.called

    # Close generator
    with pytest.raises(StopIteration):
        next(session_generator)

    mock_session.close.assert_called_once()


def test_session_acquisition_as_fastapi_dependency():
    """Verify session acquisition and automatic closure through FastAPI dependency injection."""
    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    local_app = FastAPI()

    @local_app.get("/test-session")
    def _test_route(session: Session = Depends(get_neo4j_session)):
        session.run("RETURN 1")
        return {"status": "ok"}

    local_client = TestClient(local_app)
    response = local_client.get("/test-session")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    mock_session.run.assert_called_once_with("RETURN 1")
    mock_session.close.assert_called_once()


def test_session_safely_closed_on_unhandled_route_exception():
    """Verify session is safely closed even when the route handler raises an exception."""
    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    local_app = FastAPI()

    @local_app.get("/test-session-error")
    def _test_error_route(session: Session = Depends(get_neo4j_session)):
        raise RuntimeError("Unexpected failure during request processing")

    local_client = TestClient(local_app, raise_server_exceptions=False)
    response = local_client.get("/test-session-error")

    assert response.status_code == 500
    mock_session.close.assert_called_once()


def test_successful_connectivity_verification():
    """Verify that verify_connectivity runs RETURN 1 query and returns True."""
    mock_record = {"ping": 1}
    mock_result = MagicMock()
    mock_result.single.return_value = mock_record

    mock_session = MagicMock()
    mock_session.run.return_value = mock_result

    mock_session_cm = MagicMock()
    mock_session_cm.__enter__.return_value = mock_session

    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session_cm

    result = verify_connectivity(mock_driver)
    assert result is True
    mock_driver.verify_connectivity.assert_called_once()
    mock_session.run.assert_called_once_with("RETURN 1 AS ping")


def test_connection_failure_handling_and_no_credential_leakage():
    """Verify connectivity verification handles driver errors cleanly without leaking secrets."""
    mock_driver = MagicMock()
    mock_driver.verify_connectivity.side_effect = Exception("Connection refused to bolt://secret:sensitive_token@neo4j:7687")

    with pytest.raises(Neo4jConnectionError) as exc_info:
        verify_connectivity(mock_driver)

    # Ensure sensitive credentials or raw driver strings are not leaked in exception message
    assert "sensitive_token" not in str(exc_info.value)
    assert "Failed to connect to Neo4j." in str(exc_info.value)


def test_connectivity_verification_invalid_ping_result():
    """Verify that an unexpected ping query result raises Neo4jConnectionError."""
    mock_result = MagicMock()
    mock_result.single.return_value = {"ping": 0}

    mock_session = MagicMock()
    mock_session.run.return_value = mock_result

    mock_session_cm = MagicMock()
    mock_session_cm.__enter__.return_value = mock_session

    mock_driver = MagicMock()
    mock_driver.session.return_value = mock_session_cm

    with pytest.raises(Neo4jConnectionError, match="did not return expected result"):
        verify_connectivity(mock_driver)


def test_health_neo4j_returns_200_when_available():
    """Verify GET /health/neo4j returns HTTP 200 with database indicator when available."""
    with patch("app.main.verify_connectivity", return_value=True):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/health/neo4j")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "neo4j"}


def test_health_neo4j_returns_503_when_unavailable():
    """Verify GET /health/neo4j returns HTTP 503 with safe deterministic payload when unavailable."""
    with patch("app.main.verify_connectivity", side_effect=Neo4jConnectionError("Offline")):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/health/neo4j")

        assert response.status_code == 503
        assert response.json() == {
            "status": "unavailable",
            "detail": "Neo4j service unavailable",
        }


def test_existing_health_check_remains_independent_of_neo4j():
    """Verify GET /health continues to return 200 independently of Neo4j availability."""
    # Even if Neo4j connectivity verification completely fails
    with patch("app.main.verify_connectivity", side_effect=Neo4jConnectionError("Offline")):
        client = TestClient(app, raise_server_exceptions=False)
        health_response = client.get("/health")
        assert health_response.status_code == 200
        assert health_response.json() == {"status": "ok"}
