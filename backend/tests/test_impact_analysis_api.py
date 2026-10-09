"""Automated test suite for the Impact Analysis API (P0-20).

Verifies GET /api/v1/repositories/{repository_id}/impact/{entity_id}:
1. A valid repository and entity.
2. Invalid repository IDs (empty, whitespace, null byte, traversal, length > 255 -> 400).
3. Invalid entity IDs (empty, whitespace, null byte, traversal, length > 1000 -> 400).
4. A nonexistent repository (404).
5. A nonexistent entity in an existing repository (404).
6. Direct impact (dependents at shortest-path hop depth 1).
7. Transitive impact (dependents at shortest-path hop depth > 1).
8. Affected-file extraction and deterministic path ordering.
9. Maximum traversal depth parameter handling and bounds enforcement.
10. Controlled atlas_fixture ground-truth validation (utils.format_identifier & base.BaseEntity).
11. A valid entity with zero affected dependents (returns 200 with empty collections).
12. Repository isolation preventing cross-repository entity queries or result leaks.
13. Neo4j database unavailability (503), internal error handling (500), and credential masking.
14. Exact compliance with the documented docs/API.md response schema.
"""

from pathlib import Path
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from neo4j import Driver, Session

from app.db.neo4j import Neo4jConnectionError, set_driver
from app.graph.impact import ImpactAnalysisError
from app.graph.traversal import GraphTraversalError
from app.main import app
from app.resolver import resolve_repository
from app.schemas.repository import RepositoryImpactResponse
from app.services.repository_service import validate_entity_id, validate_repository_id
from tests.test_graph_traversal import GraphSimulatorSession

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "atlas_fixture"


class FullGraphSimulatorSession(GraphSimulatorSession):
    """Extended simulator session supporting both retrieval and traversal queries."""

    def run(self, query: str, **params):
        # 1. MATCH (r:Repository {id: $repo_id})
        if "MATCH (r:Repository" in query:
            self.executed_queries.append((query, params))
            repo_id = params.get("repo_id")
            mock_res = MagicMock()
            if repo_id in self.nodes and "Repository" in self.nodes[repo_id]["labels"]:
                rec = {"props": self.nodes[repo_id]["props"]}
                mock_res.single.return_value = rec
            else:
                mock_res.single.return_value = None
            return mock_res

        # 2. MATCH (n:... {id: $entity_id}) WHERE ($repo_id IS NULL OR n.repo_id = $repo_id)
        if "RETURN properties(n) AS props" in query and "*1.." not in query:
            self.executed_queries.append((query, params))
            entity_id = params.get("entity_id")
            repo_id = params.get("repo_id")
            mock_res = MagicMock()
            if entity_id in self.nodes:
                node = self.nodes[entity_id]
                in_repo = (
                    repo_id is None
                    or node["repo_id"] == repo_id
                    or ("Repository" in node["labels"] and node["id"] == repo_id)
                )
                if in_repo:
                    rec = {"props": node["props"], "labels": node["labels"]}
                    mock_res.single.return_value = rec
                else:
                    mock_res.single.return_value = None
            else:
                mock_res.single.return_value = None
            return mock_res

        # 3. Traversal query: delegate to GraphSimulatorSession BFS engine
        return super().run(query, **params)


@pytest.fixture(autouse=True)
def reset_database_state():
    """Ensure driver state is reset before and after every test."""
    set_driver(None)
    yield
    set_driver(None)


@pytest.fixture
def fixture_simulator() -> tuple[str, FullGraphSimulatorSession]:
    """Fixture providing a populated FullGraphSimulatorSession with atlas_fixture data."""
    resolved = resolve_repository(FIXTURE_DIR, "atlas_fixture")
    repo_id = resolved.repository.id

    sim = FullGraphSimulatorSession()
    sim.add_node(repo_id, repo_id, ["Repository"], resolved.repository.to_dict())
    for f in resolved.files:
        sim.add_node(f.id, repo_id, ["File"], f.to_dict())
    for m in resolved.modules:
        sim.add_node(m.id, repo_id, ["Module"], m.to_dict())
    for c in resolved.classes:
        sim.add_node(c.id, repo_id, ["Class"], c.to_dict())
    for fn in resolved.functions:
        sim.add_node(fn.id, repo_id, ["Function"], fn.to_dict())
    for mt in resolved.methods:
        sim.add_node(mt.id, repo_id, ["Method"], mt.to_dict())
    for im in resolved.imports:
        sim.add_node(im.id, repo_id, ["Import"], im.to_dict())
    for r in resolved.relationships:
        sim.add_edge(r.source_id, r.target_id, r.rel_type.value)

    return repo_id, sim


@pytest.fixture
def client_with_fixture(fixture_simulator: tuple[str, FullGraphSimulatorSession]) -> tuple[TestClient, str]:
    """TestClient wired to a mock driver backed by the atlas_fixture simulator."""
    repo_id, sim = fixture_simulator
    driver = MagicMock(spec=Driver)
    driver.session.return_value.__enter__.return_value = sim
    set_driver(driver)
    return TestClient(app, raise_server_exceptions=False), repo_id


# ==============================================================================
# 1. Valid Repository & Entity Request
# ==============================================================================


def test_valid_repository_and_entity(client_with_fixture: tuple[TestClient, str]):
    """Verify GET /api/v1/repositories/{repo_id}/impact/{entity_id} returns 200 with valid payload."""
    client, repo_id = client_with_fixture
    target_id = "repo::atlas_fixture::function::utils.format_identifier"

    response = client.get(f"/api/v1/repositories/{repo_id}/impact/{target_id}")

    assert response.status_code == 200
    data = response.json()

    assert data["entity"]["id"] == target_id
    assert data["entity"]["name"] == "format_identifier"
    assert data["repository_id"] == repo_id
    assert isinstance(data["direct_dependents"], list)
    assert isinstance(data["transitive_dependents"], list)
    assert isinstance(data["affected_files"], list)
    assert data["max_depth"] == 10


# ==============================================================================
# 2. Invalid Repository ID (400 Bad Request)
# ==============================================================================


def test_invalid_repository_id_returns_400(client_with_fixture: tuple[TestClient, str]):
    """Verify invalid or malformed repository identifiers are rejected with 400."""
    client, _ = client_with_fixture
    target_id = "repo::atlas_fixture::function::utils.format_identifier"

    # Whitespace only
    res_spaces = client.get(f"/api/v1/repositories/%20%20/impact/{target_id}")
    assert res_spaces.status_code == 400
    assert "empty" in res_spaces.json()["detail"].lower()

    # Path traversal sequence (backslash)
    res_traversal = client.get(f"/api/v1/repositories/repo..%5C..%5Cpasswd/impact/{target_id}")
    assert res_traversal.status_code == 400
    assert "invalid" in res_traversal.json()["detail"].lower()

    # Null byte in ID
    res_null = client.get(f"/api/v1/repositories/repo%00bad/impact/{target_id}")
    assert res_null.status_code == 400
    assert "invalid" in res_null.json()["detail"].lower()

    # Excessively long repository ID
    long_id = "a" * 300
    res_long = client.get(f"/api/v1/repositories/{long_id}/impact/{target_id}")
    assert res_long.status_code == 400
    assert "maximum" in res_long.json()["detail"].lower()

    # Direct unit checks on validate_repository_id
    with pytest.raises(Exception) as exc_empty:
        validate_repository_id("")
    assert exc_empty.value.status_code == 400

    with pytest.raises(Exception) as exc_null:
        validate_repository_id("repo\0bad")
    assert exc_null.value.status_code == 400

    with pytest.raises(Exception) as exc_trav:
        validate_repository_id("../traversal")
    assert exc_trav.value.status_code == 400

    with pytest.raises(Exception) as exc_trav_win:
        validate_repository_id("..\\traversal")
    assert exc_trav_win.value.status_code == 400

    with pytest.raises(Exception) as exc_len:
        validate_repository_id("a" * 256)
    assert exc_len.value.status_code == 400


# ==============================================================================
# 3. Invalid Entity ID (400 Bad Request)
# ==============================================================================


def test_invalid_entity_id_returns_400(client_with_fixture: tuple[TestClient, str]):
    """Verify malformed or invalid entity IDs return 400 Bad Request."""
    client, repo_id = client_with_fixture

    # Whitespace only
    res_spaces = client.get(f"/api/v1/repositories/{repo_id}/impact/%20%20")
    assert res_spaces.status_code == 400
    assert "empty" in res_spaces.json()["detail"].lower()

    # Path traversal sequence (backslash)
    res_traversal = client.get(f"/api/v1/repositories/{repo_id}/impact/entity..%5C..%5Cescape")
    assert res_traversal.status_code == 400
    assert "invalid" in res_traversal.json()["detail"].lower()

    # Null byte in ID
    res_null = client.get(f"/api/v1/repositories/{repo_id}/impact/entity%00bad")
    assert res_null.status_code == 400
    assert "invalid" in res_null.json()["detail"].lower()

    # Excessively long entity ID
    long_id = "x" * 1005
    res_long = client.get(f"/api/v1/repositories/{repo_id}/impact/{long_id}")
    assert res_long.status_code == 400
    assert "maximum" in res_long.json()["detail"].lower()

    # Direct unit checks on validate_entity_id
    with pytest.raises(Exception) as exc_empty:
        validate_entity_id("")
    assert exc_empty.value.status_code == 400

    with pytest.raises(Exception) as exc_null:
        validate_entity_id("entity\0bad")
    assert exc_null.value.status_code == 400

    with pytest.raises(Exception) as exc_trav:
        validate_entity_id("../escape")
    assert exc_trav.value.status_code == 400

    with pytest.raises(Exception) as exc_trav_win:
        validate_entity_id("..\\escape")
    assert exc_trav_win.value.status_code == 400

    with pytest.raises(Exception) as exc_len:
        validate_entity_id("x" * 1001)
    assert exc_len.value.status_code == 400



# ==============================================================================
# 4. Nonexistent Repository (404 Not Found)
# ==============================================================================


def test_nonexistent_repository_returns_404(client_with_fixture: tuple[TestClient, str]):
    """Verify a syntactically valid but nonexistent repository ID returns 404 Not Found."""
    client, _ = client_with_fixture
    target_id = "repo::atlas_fixture::function::utils.format_identifier"

    response = client.get(f"/api/v1/repositories/repo_nonexistent/impact/{target_id}")

    assert response.status_code == 404
    assert "repo_nonexistent" in response.json()["detail"]
    assert "not found" in response.json()["detail"].lower()


# ==============================================================================
# 5. Nonexistent Entity in Existing Repository (404 Not Found)
# ==============================================================================


def test_nonexistent_entity_returns_404(client_with_fixture: tuple[TestClient, str]):
    """Verify a nonexistent entity ID within an existing repository returns 404 Not Found."""
    client, repo_id = client_with_fixture
    missing_entity = f"{repo_id}::function::nonexistent_symbol"

    response = client.get(f"/api/v1/repositories/{repo_id}/impact/{missing_entity}")

    assert response.status_code == 404
    assert missing_entity in response.json()["detail"]
    assert "not found" in response.json()["detail"].lower()


# ==============================================================================
# 6. Direct Impact (Depth == 1)
# ==============================================================================


def test_direct_impact_depth_one(client_with_fixture: tuple[TestClient, str]):
    """Verify direct dependents are strictly at hop distance 1."""
    client, repo_id = client_with_fixture
    target_id = "repo::atlas_fixture::function::utils.format_identifier"

    response = client.get(f"/api/v1/repositories/{repo_id}/impact/{target_id}")

    assert response.status_code == 200
    data = response.json()

    # utils.format_identifier is called directly by services.ItemService.create_tagged_item (depth 1)
    direct = data["direct_dependents"]
    assert len(direct) == 1
    assert direct[0]["id"] == "repo::atlas_fixture::method::services.ItemService.create_tagged_item"
    assert direct[0]["depth"] == 1
    assert direct[0]["name"] == "create_tagged_item"


# ==============================================================================
# 7. Transitive Impact (Depth > 1)
# ==============================================================================


def test_transitive_impact_depth_greater_than_one(client_with_fixture: tuple[TestClient, str]):
    """Verify transitive dependents are strictly at hop distances > 1."""
    client, repo_id = client_with_fixture
    target_id = "repo::atlas_fixture::function::utils.format_identifier"

    response = client.get(f"/api/v1/repositories/{repo_id}/impact/{target_id}")

    assert response.status_code == 200
    data = response.json()

    transitive = data["transitive_dependents"]
    assert len(transitive) == 2

    # services.process_item_workflow (depth 2) and app.main (depth 3)
    transitive_ids = {dep["id"] for dep in transitive}
    assert "repo::atlas_fixture::function::services.process_item_workflow" in transitive_ids
    assert "repo::atlas_fixture::function::app.main" in transitive_ids

    for dep in transitive:
        assert dep["depth"] > 1


# ==============================================================================
# 8. Affected-File Extraction and Deterministic Ordering
# ==============================================================================


def test_affected_files_extraction_and_deterministic_ordering(client_with_fixture: tuple[TestClient, str]):
    """Verify affected files are extracted from impacted entities and sorted deterministically."""
    client, repo_id = client_with_fixture
    target_id = "repo::atlas_fixture::function::utils.format_identifier"

    response = client.get(f"/api/v1/repositories/{repo_id}/impact/{target_id}")

    assert response.status_code == 200
    data = response.json()

    # Ground truth: services.ItemService (services.py), process_item_workflow (services.py), app.main (app.py)
    # Deduplicated and deterministically sorted by path ASC: ["app.py", "services.py"]
    assert data["affected_files"] == ["app.py", "services.py"]

    # Verify repeated calls return identical deterministic ordering
    response2 = client.get(f"/api/v1/repositories/{repo_id}/impact/{target_id}")
    assert response2.json()["affected_files"] == data["affected_files"]
    assert response2.json()["direct_dependents"] == data["direct_dependents"]
    assert response2.json()["transitive_dependents"] == data["transitive_dependents"]


# ==============================================================================
# 9. Maximum Traversal Depth Handling & Bounds
# ==============================================================================


def test_max_depth_query_parameter_limits_traversal(client_with_fixture: tuple[TestClient, str]):
    """Verify max_depth query parameter bounds traversal depth."""
    client, repo_id = client_with_fixture
    target_id = "repo::atlas_fixture::function::utils.format_identifier"

    # Depth 1: Only direct dependent reached, 0 transitive dependents, only services.py affected
    res_depth_1 = client.get(f"/api/v1/repositories/{repo_id}/impact/{target_id}?max_depth=1")
    assert res_depth_1.status_code == 200
    data_1 = res_depth_1.json()
    assert data_1["max_depth"] == 1
    assert len(data_1["direct_dependents"]) == 1
    assert len(data_1["transitive_dependents"]) == 0
    assert data_1["affected_files"] == ["services.py"]

    # Depth 2: Direct dependent + process_item_workflow (depth 2), app.main (depth 3) excluded
    res_depth_2 = client.get(f"/api/v1/repositories/{repo_id}/impact/{target_id}?max_depth=2")
    assert res_depth_2.status_code == 200
    data_2 = res_depth_2.json()
    assert data_2["max_depth"] == 2
    assert len(data_2["direct_dependents"]) == 1
    assert len(data_2["transitive_dependents"]) == 1
    assert data_2["transitive_dependents"][0]["depth"] == 2
    assert data_2["affected_files"] == ["services.py"]

    # Depth 3: All 3 dependents reached
    res_depth_3 = client.get(f"/api/v1/repositories/{repo_id}/impact/{target_id}?max_depth=3")
    assert res_depth_3.status_code == 200
    data_3 = res_depth_3.json()
    assert data_3["max_depth"] == 3
    assert len(data_3["direct_dependents"]) == 1
    assert len(data_3["transitive_dependents"]) == 2
    assert data_3["affected_files"] == ["app.py", "services.py"]


@pytest.mark.parametrize("invalid_depth", [0, -1, -10])
def test_invalid_max_depth_returns_422_or_400(client_with_fixture: tuple[TestClient, str], invalid_depth: int):
    """Verify max_depth < 1 is rejected by request validation."""
    client, repo_id = client_with_fixture
    target_id = "repo::atlas_fixture::function::utils.format_identifier"

    response = client.get(f"/api/v1/repositories/{repo_id}/impact/{target_id}?max_depth={invalid_depth}")
    assert response.status_code in (400, 422)


# ==============================================================================
# 10. Controlled atlas_fixture Ground-Truth Validation
# ==============================================================================


def test_atlas_fixture_ground_truth_format_identifier(client_with_fixture: tuple[TestClient, str]):
    """Verify impact of utils.format_identifier matches README.md section 11.2."""
    client, repo_id = client_with_fixture
    target_id = "repo::atlas_fixture::function::utils.format_identifier"

    response = client.get(f"/api/v1/repositories/{repo_id}/impact/{target_id}")
    assert response.status_code == 200
    data = response.json()

    # Direct: services.ItemService.create_tagged_item (depth 1)
    assert len(data["direct_dependents"]) == 1
    assert data["direct_dependents"][0]["name"] == "create_tagged_item"

    # Transitive: services.process_item_workflow (depth 2), app.main (depth 3)
    assert len(data["transitive_dependents"]) == 2
    transitive_names = [d["name"] for d in data["transitive_dependents"]]
    assert "process_item_workflow" in transitive_names
    assert "main" in transitive_names

    # Affected files
    assert data["affected_files"] == ["app.py", "services.py"]

    # Negative isolation: Unaffected files must not appear in affected_files
    for unaffected in ["utils.py", "models.py", "base.py", "unrelated.py", "ambiguous.py"]:
        assert unaffected not in data["affected_files"]


def test_atlas_fixture_ground_truth_base_entity(client_with_fixture: tuple[TestClient, str]):
    """Verify impact of base.BaseEntity class matches README.md section 11.1."""
    client, repo_id = client_with_fixture
    base_class_id = "repo::atlas_fixture::class::base.BaseEntity"

    response = client.get(f"/api/v1/repositories/{repo_id}/impact/{base_class_id}")
    assert response.status_code == 200
    data = response.json()

    # Direct dependent: models.ItemModel (via INHERITS)
    assert len(data["direct_dependents"]) == 1
    assert data["direct_dependents"][0]["name"] == "ItemModel"
    assert data["direct_dependents"][0]["depth"] == 1

    # Affected files: models.py
    assert data["affected_files"] == ["models.py"]


# ==============================================================================
# 11. Valid Entity With Zero Affected Dependents (200 OK)
# ==============================================================================


def test_valid_entity_with_no_dependents_returns_empty_results(client_with_fixture: tuple[TestClient, str]):
    """Verify a valid leaf entity returns 200 with empty direct/transitive dependents and affected files."""
    client, repo_id = client_with_fixture
    # app.main is the root caller; nothing depends on or calls main
    main_id = "repo::atlas_fixture::function::app.main"

    response = client.get(f"/api/v1/repositories/{repo_id}/impact/{main_id}")

    assert response.status_code == 200
    data = response.json()

    assert data["entity"]["id"] == main_id
    assert data["entity"]["name"] == "main"
    assert data["direct_dependents"] == []
    assert data["transitive_dependents"] == []
    assert data["affected_files"] == []
    assert data["max_depth"] == 10


# ==============================================================================
# 12. Repository Isolation & Cross-Repository Protection
# ==============================================================================


def test_cross_repository_entity_isolation(client_with_fixture: tuple[TestClient, str]):
    """Verify querying an entity belonging to another repository returns 404 and leaks no results."""
    client, repo_id = client_with_fixture
    other_repo_entity = "repo::other_repository::function::foreign_symbol"

    response = client.get(f"/api/v1/repositories/{repo_id}/impact/{other_repo_entity}")

    assert response.status_code == 404
    assert "not found in repository" in response.json()["detail"].lower()


# ==============================================================================
# 13. Neo4j Unavailability (503) & Error Handling (500)
# ==============================================================================


def test_neo4j_database_unavailable_returns_503():
    """Verify Neo4j connection failure returns 503 Service Unavailable."""
    mock_driver = MagicMock(spec=Driver)
    mock_session = MagicMock(spec=Session)
    mock_driver.session.return_value.__enter__.return_value = mock_session
    mock_session.run.side_effect = Neo4jConnectionError("Failed to establish connection to bolt://classified:7687")

    set_driver(mock_driver)
    test_client = TestClient(app, raise_server_exceptions=False)

    response = test_client.get(
        "/api/v1/repositories/repo_001/impact/repo_001::function::foo"
    )

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()
    assert "classified" not in response.text


def test_driver_uninitialized_returns_503():
    """Verify missing/uninitialized driver returns 503 Service Unavailable."""
    set_driver(None)
    test_client = TestClient(app, raise_server_exceptions=False)

    response = test_client.get(
        "/api/v1/repositories/repo_001/impact/repo_001::function::foo"
    )

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()


def test_internal_error_returns_500_and_masks_credentials(fixture_simulator: tuple[str, FullGraphSimulatorSession]):
    """Verify unexpected analysis errors return 500 Internal Server Error without leaking secrets."""
    repo_id, sim = fixture_simulator
    target_id = "repo::atlas_fixture::function::utils.format_identifier"

    driver = MagicMock(spec=Driver)
    driver.session.return_value.__enter__.return_value = sim

    # Simulate an internal failure during traversal with sensitive info
    with pytest.MonkeyPatch.context() as mp:
        def failing_analyze(*args, **kwargs):
            raise ImpactAnalysisError("Fatal error at bolt://neo4j:super_secret_password@db:7687")

        mp.setattr("app.graph.impact.ImpactAnalyzer.analyze_impact", failing_analyze)
        set_driver(driver)
        test_client = TestClient(app, raise_server_exceptions=False)

        response = test_client.get(f"/api/v1/repositories/{repo_id}/impact/{target_id}")

    assert response.status_code == 500
    assert "super_secret_password" not in response.text
    assert "detail" in response.json()


# ==============================================================================
# 14. Compliance With Documented Response Schema (docs/API.md)
# ==============================================================================


def test_response_schema_compliance(client_with_fixture: tuple[TestClient, str]):
    """Verify the response matches the documented docs/API.md schema contract exactly."""
    client, repo_id = client_with_fixture
    target_id = "repo::atlas_fixture::function::utils.format_identifier"

    response = client.get(f"/api/v1/repositories/{repo_id}/impact/{target_id}")
    assert response.status_code == 200
    data = response.json()

    # 1. Top-level required keys matching docs/API.md
    assert "entity" in data
    assert "direct_dependents" in data
    assert "transitive_dependents" in data
    assert "affected_files" in data
    assert "max_depth" in data

    # 2. Entity object contract
    assert isinstance(data["entity"], dict)
    assert "id" in data["entity"]
    assert "name" in data["entity"]
    assert data["entity"]["id"] == target_id
    assert data["entity"]["name"] == "format_identifier"

    # 3. Direct dependents list
    assert isinstance(data["direct_dependents"], list)
    for dep in data["direct_dependents"]:
        assert "id" in dep
        assert "name" in dep
        assert "depth" in dep
        assert dep["depth"] == 1

    # 4. Transitive dependents list
    assert isinstance(data["transitive_dependents"], list)
    for dep in data["transitive_dependents"]:
        assert "id" in dep
        assert "name" in dep
        assert "depth" in dep
        assert dep["depth"] > 1

    # 5. Affected files list
    assert isinstance(data["affected_files"], list)
    for f in data["affected_files"]:
        assert isinstance(f, str)

    # 6. Max depth int
    assert isinstance(data["max_depth"], int)
    assert data["max_depth"] == 10

    # 7. Validates against Pydantic schema
    validated = RepositoryImpactResponse.model_validate(data)
    assert validated.entity.id == target_id
    assert validated.max_depth == 10


# ==============================================================================
# 15. Read-Only Invariant Test
# ==============================================================================


def test_impact_analysis_api_is_strictly_read_only(
    client_with_fixture: tuple[TestClient, str],
    fixture_simulator: tuple[str, FullGraphSimulatorSession],
):
    """Verify GET /impact is non-mutating and performs zero database writes."""
    client, repo_id = client_with_fixture
    _, sim = fixture_simulator
    target_id = "repo::atlas_fixture::function::utils.format_identifier"

    initial_node_count = len(sim.nodes)
    initial_edge_count = len(sim.edges)

    response = client.get(f"/api/v1/repositories/{repo_id}/impact/{target_id}")
    assert response.status_code == 200

    assert len(sim.nodes) == initial_node_count
    assert len(sim.edges) == initial_edge_count

    # Check executed Cypher queries contain no mutating clauses
    for q, _ in sim.executed_queries:
        upper = q.upper()
        for forbidden in ["CREATE ", "MERGE ", "SET ", "DELETE ", "REMOVE ", "DROP "]:
            assert forbidden not in upper
