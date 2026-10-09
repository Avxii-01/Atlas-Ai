"""Automated test suite for the Repository Analysis API (P0-18).

Verifies POST /api/v1/repositories/analyze:
- Request validation and filesystem safety.
- Static analysis pipeline execution against tests/fixtures/atlas_fixture.
- Ordered entity and relationship persistence in Neo4j.
- Deterministic response contract matching docs/API.md.
- Robust error handling and credential masking.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from neo4j import Driver, Session

from app.db.entity_persister import Neo4jPersistenceError
from app.db.neo4j import Neo4jConnectionError, set_driver
from app.db.relationship_persister import Neo4jRelationshipPersistenceError
from app.main import app
from app.services.repository_service import reset_schema_initialization_flag

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "atlas_fixture"


@pytest.fixture(autouse=True)
def reset_database_and_schema_state():
    """Ensure driver state and schema cache are reset before and after every test."""
    set_driver(None)
    reset_schema_initialization_flag()
    yield
    set_driver(None)
    reset_schema_initialization_flag()


@pytest.fixture
def mock_driver() -> MagicMock:
    """Fixture providing a configured mock Neo4j Driver and Session."""
    driver = MagicMock(spec=Driver)
    session = MagicMock(spec=Session)
    driver.session.return_value.__enter__.return_value = session
    session.run.return_value = [{"persisted_count": 1}]
    return driver


@pytest.fixture
def client(mock_driver: MagicMock) -> TestClient:
    """Fixture providing a TestClient configured with a mock Neo4j driver."""
    set_driver(mock_driver)
    return TestClient(app, raise_server_exceptions=False)


# ==============================================================================
# 1. Successful Analysis & Response Contract Tests
# ==============================================================================


def test_analyze_repository_fixture_success(client: TestClient, mock_driver: MagicMock):
    """Verify POST /api/v1/repositories/analyze executes successfully for the Atlas fixture."""
    payload = {"path": str(FIXTURE_DIR)}
    response = client.post("/api/v1/repositories/analyze", json=payload)

    assert response.status_code == 200
    data = response.json()

    # Verify response schema conforms to docs/API.md
    assert data["repository_id"] == "repo::atlas_fixture"
    assert data["status"] == "completed"

    summary = data["summary"]
    # Exact ground truth from tests/fixtures/atlas_fixture/README.md
    assert summary["files"] == 7
    assert summary["classes"] == 7
    assert summary["functions"] == 11
    assert summary["relationships"] == 58
    assert summary["modules"] == 7
    assert summary["methods"] == 12
    assert summary["imports"] == 8

    # Verify Neo4j session was invoked
    assert mock_driver.session.called


def test_analyze_repository_custom_name_and_source(client: TestClient):
    """Verify POST /api/v1/repositories/analyze respects custom repository name and source."""
    payload = {
        "path": str(FIXTURE_DIR),
        "name": "custom_project",
        "source": "https://github.com/example/custom_project",
    }
    response = client.post("/api/v1/repositories/analyze", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["repository_id"] == "repo::custom_project"
    assert data["status"] == "completed"


def test_analyze_repository_alias_fields(client: TestClient):
    """Verify request model accepts alias fields 'repo_path' and 'repo_name'."""
    payload = {
        "repo_path": str(FIXTURE_DIR),
        "repo_name": "aliased_project",
    }
    response = client.post("/api/v1/repositories/analyze", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["repository_id"] == "repo::aliased_project"
    assert data["status"] == "completed"


def test_repeated_analysis_idempotency(client: TestClient, mock_driver: MagicMock):
    """Verify analyzing the same repository repeatedly produces identical, idempotent results."""
    payload = {"path": str(FIXTURE_DIR)}

    resp1 = client.post("/api/v1/repositories/analyze", json=payload)
    resp2 = client.post("/api/v1/repositories/analyze", json=payload)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json() == resp2.json()


# ==============================================================================
# 2. Pipeline Orchestration & Persistence Ordering Tests
# ==============================================================================


def test_pipeline_orchestration_persists_entities_before_relationships(client: TestClient):
    """Verify that entity persistence is invoked before relationship persistence."""
    call_order: list[str] = []

    with patch("app.services.repository_service.persist_entities") as mock_persist_ent, \
         patch("app.services.repository_service.persist_relationships") as mock_persist_rel:

        mock_persist_ent.side_effect = lambda ucm, **kw: call_order.append("entities")
        mock_persist_rel.side_effect = lambda ucm, **kw: call_order.append("relationships")

        payload = {"path": str(FIXTURE_DIR)}
        response = client.post("/api/v1/repositories/analyze", json=payload)

        assert response.status_code == 200
        assert call_order == ["entities", "relationships"]
        assert mock_persist_ent.called
        assert mock_persist_rel.called


# ==============================================================================
# 3. Request Validation & Filesystem Safety Tests
# ==============================================================================


def test_validation_rejects_missing_path(client: TestClient, mock_driver: MagicMock):
    """Verify request lacking a path parameter is rejected with HTTP 422."""
    response = client.post("/api/v1/repositories/analyze", json={})

    assert response.status_code == 422
    assert not mock_driver.session.called


def test_validation_rejects_empty_path(client: TestClient, mock_driver: MagicMock):
    """Verify request with an empty path is rejected."""
    response = client.post("/api/v1/repositories/analyze", json={"path": "   "})

    assert response.status_code == 422
    assert not mock_driver.session.called


def test_validation_rejects_nonexistent_path(client: TestClient, mock_driver: MagicMock):
    """Verify nonexistent filesystem path is rejected with HTTP 400."""
    response = client.post(
        "/api/v1/repositories/analyze",
        json={"path": "tests/fixtures/nonexistent_folder_abc123"},
    )

    assert response.status_code == 400
    assert "does not exist" in response.json()["detail"].lower()
    assert not mock_driver.session.called


def test_validation_rejects_file_instead_of_directory(client: TestClient, mock_driver: MagicMock):
    """Verify pointing to a single file instead of a directory is rejected with HTTP 400."""
    file_path = FIXTURE_DIR / "app.py"
    response = client.post(
        "/api/v1/repositories/analyze",
        json={"path": str(file_path)},
    )

    assert response.status_code == 400
    assert "must be a directory" in response.json()["detail"].lower()
    assert not mock_driver.session.called


def test_validation_rejects_root_directory(client: TestClient, mock_driver: MagicMock):
    """Verify root filesystem directories cannot be scanned."""
    response = client.post(
        "/api/v1/repositories/analyze",
        json={"path": "C:\\"},
    )

    assert response.status_code == 400
    assert "not permitted" in response.json()["detail"].lower()
    assert not mock_driver.session.called


def test_validation_rejects_system_directory(client: TestClient, mock_driver: MagicMock):
    """Verify sensitive operating system directories cannot be scanned."""
    response = client.post(
        "/api/v1/repositories/analyze",
        json={"path": "C:\\Windows"},
    )

    assert response.status_code == 400
    assert "not permitted" in response.json()["detail"].lower()
    assert not mock_driver.session.called


# ==============================================================================
# 4. Error Handling & Failure Recovery Tests
# ==============================================================================


def test_failure_database_connection_unavailable(mock_driver: MagicMock):
    """Verify Neo4j unavailability returns HTTP 503 without leaking secrets."""
    set_driver(None)  # Driver uninitialized
    unconnected_client = TestClient(app, raise_server_exceptions=False)

    payload = {"path": str(FIXTURE_DIR)}
    response = unconnected_client.post("/api/v1/repositories/analyze", json=payload)

    assert response.status_code == 503
    assert "database service unavailable" in response.json()["detail"].lower()


def test_failure_entity_persistence_error(client: TestClient):
    """Verify entity persistence failure returns HTTP 500 and skips relationship persistence."""
    with patch("app.services.repository_service.persist_entities") as mock_persist_ent, \
         patch("app.services.repository_service.persist_relationships") as mock_persist_rel:

        mock_persist_ent.side_effect = Neo4jPersistenceError("Simulated entity persistence crash")

        payload = {"path": str(FIXTURE_DIR)}
        response = client.post("/api/v1/repositories/analyze", json=payload)

        assert response.status_code == 500
        assert "failed to persist repository entities" in response.json()["detail"].lower()
        assert not mock_persist_rel.called


def test_failure_relationship_persistence_error(client: TestClient):
    """Verify relationship persistence failure returns HTTP 500 rather than false success."""
    with patch("app.services.repository_service.persist_relationships") as mock_persist_rel:
        mock_persist_rel.side_effect = Neo4jRelationshipPersistenceError("Simulated relationship persistence crash")

        payload = {"path": str(FIXTURE_DIR)}
        response = client.post("/api/v1/repositories/analyze", json=payload)

        assert response.status_code == 500
        assert "failed to persist repository relationships" in response.json()["detail"].lower()


def test_failure_pipeline_internal_error(client: TestClient):
    """Verify unexpected failure in static analysis pipeline returns HTTP 500."""
    with patch("app.services.repository_service.resolve_repository") as mock_resolve:
        mock_resolve.side_effect = RuntimeError("Parser crashed unexpectedly")

        payload = {"path": str(FIXTURE_DIR)}
        response = client.post("/api/v1/repositories/analyze", json=payload)

        assert response.status_code == 500
        assert "static analysis pipeline failed" in response.json()["detail"].lower()


def test_error_handling_masks_credentials(client: TestClient):
    """Verify exceptions containing connection URIs mask passwords in client responses."""
    with patch("app.services.repository_service.persist_entities") as mock_persist_ent:
        mock_persist_ent.side_effect = Exception("Auth failed for bolt://user:super_secret_pw@neo4j:7687")

        payload = {"path": str(FIXTURE_DIR)}
        response = client.post("/api/v1/repositories/analyze", json=payload)

        assert response.status_code == 500
        assert "super_secret_pw" not in response.text
