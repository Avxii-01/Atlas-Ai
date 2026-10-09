"""Automated test suite for the Repository Graph API (P0-19).

Verifies GET /api/v1/repositories/{repository_id}/graph:
- Valid repository requests returning documented schema and ground truth.
- Serialization of all 7 UCM entity types and 4 relationship types.
- Strict relationship direction and endpoint presence invariants.
- Deterministic ordering of nodes and edges across repeated calls.
- Nonexistent repository (404), empty repository (200), and invalid ID (400) handling.
- Database connection failure (503) and internal retrieval error (500) handling.
- Credential masking in public error messages.
- Read-only guarantees (zero graph mutation or persistence calls).
- Controlled fixture validation against tests/fixtures/atlas_fixture ground truth.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from neo4j import Driver, Record, Session

from app.db.graph_retriever import GraphRetriever, Neo4jRetrievalError
from app.db.neo4j import Neo4jConnectionError, set_driver
from app.main import app
from app.resolver import resolve_repository
from app.services.repository_service import (
    RepositoryService,
    serialize_ucm_graph,
    validate_repository_id,
)
from app.ucm.entities import Class, File, Function, Import, Method, Module, Repository
from app.ucm.model import UnifiedCodeModel
from app.ucm.relationships import Relationship, RelationshipType

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "atlas_fixture"


@pytest.fixture(autouse=True)
def reset_database_state():
    """Ensure driver state is reset before and after every test."""
    set_driver(None)
    yield
    set_driver(None)


@pytest.fixture
def resolved_fixture_ucm() -> UnifiedCodeModel:
    """Fixture providing ground-truth UnifiedCodeModel from atlas_fixture."""
    return resolve_repository(FIXTURE_DIR, "atlas_fixture")


@pytest.fixture
def mock_driver() -> MagicMock:
    """Fixture providing a mock Neo4j driver."""
    driver = MagicMock(spec=Driver)
    session = MagicMock(spec=Session)
    driver.session.return_value.__enter__.return_value = session
    return driver


@pytest.fixture
def client(mock_driver: MagicMock) -> TestClient:
    """Fixture providing a TestClient with a mock driver active."""
    set_driver(mock_driver)
    return TestClient(app, raise_server_exceptions=False)


# ==============================================================================
# 1. Valid Request & Controlled Fixture Ground Truth Tests
# ==============================================================================


def test_get_repository_graph_fixture_success(
    client: TestClient,
    resolved_fixture_ucm: UnifiedCodeModel,
):
    """Verify GET /api/v1/repositories/{repository_id}/graph against atlas_fixture ground truth."""
    repo_id = resolved_fixture_ucm.repository.id

    with patch.object(GraphRetriever, "get_repository_graph", return_value=resolved_fixture_ucm):
        response = client.get(f"/api/v1/repositories/{repo_id}/graph")

    assert response.status_code == 200
    data = response.json()

    # Response schema validation according to docs/API.md
    assert "repository_id" in data
    assert "nodes" in data
    assert "relationships" in data

    assert data["repository_id"] == repo_id
    assert isinstance(data["nodes"], list)
    assert isinstance(data["relationships"], list)

    # Ground truth verification:
    # 1 repository + 7 files + 7 modules + 7 classes + 11 functions + 12 methods + 8 imports = 53 nodes
    assert len(data["nodes"]) == 53

    # Total relationships invariant: 37 CONTAINS + 5 IMPORTS + 15 CALLS + 1 INHERITS = 58
    assert len(data["relationships"]) == 58


def test_get_repository_graph_counts_per_entity_and_rel_type(
    client: TestClient,
    resolved_fixture_ucm: UnifiedCodeModel,
):
    """Verify count breakdowns per node label and relationship type match ground truth."""
    repo_id = resolved_fixture_ucm.repository.id

    with patch.object(GraphRetriever, "get_repository_graph", return_value=resolved_fixture_ucm):
        response = client.get(f"/api/v1/repositories/{repo_id}/graph")

    assert response.status_code == 200
    data = response.json()

    # Count nodes per label
    label_counts: dict[str, int] = {}
    for node in data["nodes"]:
        label_counts[node["label"]] = label_counts.get(node["label"], 0) + 1

    assert label_counts["Repository"] == 1
    assert label_counts["File"] == 7
    assert label_counts["Module"] == 7
    assert label_counts["Class"] == 7
    assert label_counts["Function"] == 11
    assert label_counts["Method"] == 12
    assert label_counts["Import"] == 8

    # Count relationships per type
    rel_counts: dict[str, int] = {}
    for edge in data["relationships"]:
        rel_counts[edge["type"]] = rel_counts.get(edge["type"], 0) + 1

    assert rel_counts["CONTAINS"] == 37
    assert rel_counts["IMPORTS"] == 5
    assert rel_counts["CALLS"] == 15
    assert rel_counts["INHERITS"] == 1


# ==============================================================================
# 2. Serialization Correctness & Invariants
# ==============================================================================


def test_node_serialization_preserves_required_fields(
    client: TestClient,
    resolved_fixture_ucm: UnifiedCodeModel,
):
    """Verify serialized nodes possess stable IDs, labels, display names, and properties."""
    repo_id = resolved_fixture_ucm.repository.id

    with patch.object(GraphRetriever, "get_repository_graph", return_value=resolved_fixture_ucm):
        response = client.get(f"/api/v1/repositories/{repo_id}/graph")

    assert response.status_code == 200
    nodes = response.json()["nodes"]

    for node in nodes:
        assert isinstance(node["id"], str) and node["id"]
        assert isinstance(node["label"], str) and node["label"]
        assert isinstance(node["name"], str) and node["name"]
        assert node["type"] == node["label"]
        assert isinstance(node["properties"], dict)

    # Check a specific representative class node
    class_node = next(n for n in nodes if n["id"] == "repo::atlas_fixture::class::models.ItemModel")
    assert class_node["label"] == "Class"
    assert class_node["name"] == "ItemModel"
    assert class_node["properties"]["qualified_name"] == "models.ItemModel"
    assert class_node["properties"]["file_path"] == "models.py"
    assert class_node["properties"]["language"] == "python"


def test_edge_serialization_preserves_direction_and_endpoints(
    client: TestClient,
    resolved_fixture_ucm: UnifiedCodeModel,
):
    """Verify relationship edges preserve direction and endpoint presence in the node set."""
    repo_id = resolved_fixture_ucm.repository.id

    with patch.object(GraphRetriever, "get_repository_graph", return_value=resolved_fixture_ucm):
        response = client.get(f"/api/v1/repositories/{repo_id}/graph")

    assert response.status_code == 200
    data = response.json()

    node_ids = {node["id"] for node in data["nodes"]}

    for edge in data["relationships"]:
        assert isinstance(edge["id"], str) and edge["id"]
        assert edge["source"] in node_ids, f"Edge source {edge['source']} missing from nodes"
        assert edge["target"] in node_ids, f"Edge target {edge['target']} missing from nodes"
        assert edge["source_id"] == edge["source"]
        assert edge["target_id"] == edge["target"]
        assert edge["rel_type"] == edge["type"]
        assert edge["type"] in {"CONTAINS", "IMPORTS", "CALLS", "INHERITS"}

    # Verify inheritance edge direction: ItemModel -> INHERITS -> BaseEntity
    inherits_edge = next(e for e in data["relationships"] if e["type"] == "INHERITS")
    assert inherits_edge["source"] == "repo::atlas_fixture::class::models.ItemModel"
    assert inherits_edge["target"] == "repo::atlas_fixture::class::base.BaseEntity"


def test_serialization_enforces_endpoint_existence_filter():
    """Verify edges referencing missing nodes are excluded from serialization."""
    repo = Repository(id="repo::test", name="test", source="local")
    file1 = File.create(repo_id="repo::test", path="app.py", language="python", start_line=1, end_line=10)
    ucm = UnifiedCodeModel(repository=repo)
    ucm.add_file(file1)

    # Valid edge between repo and file1
    rel_valid = Relationship(
        rel_type=RelationshipType.CONTAINS,
        source_id=repo.id,
        target_id=file1.id,
    )
    # Dangling edge to an unpersisted entity
    rel_dangling = Relationship(
        rel_type=RelationshipType.CALLS,
        source_id=file1.id,
        target_id="repo::test::function::ghost_function",
    )
    ucm.add_relationship(rel_valid)
    ucm.add_relationship(rel_dangling)

    nodes, edges = serialize_ucm_graph(ucm)
    assert len(nodes) == 2  # repo + file1
    assert len(edges) == 1  # only rel_valid preserved
    assert edges[0].target == file1.id


def test_deterministic_ordering_across_repeated_calls(
    client: TestClient,
    resolved_fixture_ucm: UnifiedCodeModel,
):
    """Verify repeated retrieval produces identical, deterministic node and edge order."""
    repo_id = resolved_fixture_ucm.repository.id

    with patch.object(GraphRetriever, "get_repository_graph", return_value=resolved_fixture_ucm):
        res1 = client.get(f"/api/v1/repositories/{repo_id}/graph").json()
        res2 = client.get(f"/api/v1/repositories/{repo_id}/graph").json()

    assert [n["id"] for n in res1["nodes"]] == [n["id"] for n in res2["nodes"]]
    assert [e["id"] for e in res1["relationships"]] == [e["id"] for e in res2["relationships"]]


# ==============================================================================
# 3. Missing, Empty, and Invalid Repository Handling
# ==============================================================================


def test_nonexistent_repository_returns_404(client: TestClient):
    """Verify a syntactically valid but nonexistent repository returns 404."""
    with patch.object(GraphRetriever, "get_repository_graph", return_value=None):
        response = client.get("/api/v1/repositories/repo::nonexistent/graph")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_empty_repository_returns_200_with_empty_collections(client: TestClient):
    """Verify an existing repository with no entities returns 200 with repository node and empty edges."""
    repo = Repository(id="repo::empty_repo", name="empty_repo", source="local")
    empty_ucm = UnifiedCodeModel(repository=repo)

    with patch.object(GraphRetriever, "get_repository_graph", return_value=empty_ucm):
        response = client.get("/api/v1/repositories/repo::empty_repo/graph")

    assert response.status_code == 200
    data = response.json()
    assert data["repository_id"] == "repo::empty_repo"
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["label"] == "Repository"
    assert data["relationships"] == []


def test_invalid_repository_id_returns_400(client: TestClient):
    """Verify invalid or malformed repository identifiers are rejected with 400."""
    # Whitespace only
    res_spaces = client.get("/api/v1/repositories/%20%20/graph")
    assert res_spaces.status_code == 400
    assert "empty" in res_spaces.json()["detail"].lower()

    # Path traversal sequence (backslash)
    res_traversal = client.get("/api/v1/repositories/repo..%5C..%5Cpasswd/graph")
    assert res_traversal.status_code == 400
    assert "invalid" in res_traversal.json()["detail"].lower()

    # Null byte in ID
    res_null = client.get("/api/v1/repositories/repo%00bad/graph")
    assert res_null.status_code == 400
    assert "invalid" in res_null.json()["detail"].lower()

    # Excessively long repository ID
    long_id = "a" * 300
    res_long = client.get(f"/api/v1/repositories/{long_id}/graph")
    assert res_long.status_code == 400
    assert "maximum" in res_long.json()["detail"].lower()


# ==============================================================================
# 4. Error Handling and Security
# ==============================================================================


def test_neo4j_database_unavailable_returns_503(client: TestClient):
    """Verify Neo4j connection failure returns 503 without leaking credentials."""
    with patch.object(
        GraphRetriever,
        "get_repository_graph",
        side_effect=Neo4jConnectionError("neo4j://neo4j:supersecret@localhost:7687 connection refused"),
    ):
        response = client.get("/api/v1/repositories/repo::atlas_fixture/graph")

    assert response.status_code == 503
    assert response.json()["detail"] == "Database service unavailable"
    assert "supersecret" not in response.text
    assert "7687" not in response.text


def test_graph_retrieval_failure_returns_500(client: TestClient):
    """Verify internal retrieval/query failure returns 500 without leaking stack traces."""
    with patch.object(
        GraphRetriever,
        "get_repository_graph",
        side_effect=RuntimeError("Unexpected internal parser failure"),
    ):
        response = client.get("/api/v1/repositories/repo::atlas_fixture/graph")

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to retrieve repository graph"
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text


# ==============================================================================
# 5. Read-Only Verification
# ==============================================================================


def test_get_repository_graph_is_strictly_read_only(
    client: TestClient,
    resolved_fixture_ucm: UnifiedCodeModel,
):
    """Verify endpoint never invokes persistence or schema mutation methods."""
    with (
        patch("app.db.entity_persister.persist_entities") as mock_persist_entities,
        patch("app.db.relationship_persister.persist_relationships") as mock_persist_relationships,
        patch("app.db.schema.init_schema") as mock_init_schema,
        patch.object(GraphRetriever, "get_repository_graph", return_value=resolved_fixture_ucm),
    ):
        response = client.get(f"/api/v1/repositories/{resolved_fixture_ucm.repository.id}/graph")

    assert response.status_code == 200
    mock_persist_entities.assert_not_called()
    mock_persist_relationships.assert_not_called()
    mock_init_schema.assert_not_called()


# ==============================================================================
# 6. Optional Query Parameter Filtering
# ==============================================================================


def test_get_repository_graph_with_limit_query_parameter(
    client: TestClient,
    resolved_fixture_ucm: UnifiedCodeModel,
):
    """Verify limit query parameter slices nodes and constrains relationships."""
    repo_id = resolved_fixture_ucm.repository.id

    with patch.object(GraphRetriever, "get_repository_graph", return_value=resolved_fixture_ucm):
        response = client.get(f"/api/v1/repositories/{repo_id}/graph?limit=5")

    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 5

    # Every returned edge must connect only nodes in the sliced 5 nodes
    node_ids = {n["id"] for n in data["nodes"]}
    for edge in data["relationships"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids

    # Repository root must be present as the first node
    assert data["nodes"][0]["label"] == "Repository"
    assert data["nodes"][0]["id"] == repo_id


def test_limit_preserves_repository_root_on_limit_1(
    client: TestClient,
    resolved_fixture_ucm: UnifiedCodeModel,
):
    """Verify limit=1 returns the repository root node and zero relationships."""
    repo_id = resolved_fixture_ucm.repository.id

    with patch.object(GraphRetriever, "get_repository_graph", return_value=resolved_fixture_ucm):
        response = client.get(f"/api/v1/repositories/{repo_id}/graph?limit=1")

    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["label"] == "Repository"
    assert data["nodes"][0]["id"] == repo_id
    assert data["relationships"] == []


def test_limit_rejects_invalid_values(client: TestClient):
    """Verify limit values less than 1 or non-integers are rejected with 422."""
    res_zero = client.get("/api/v1/repositories/repo::atlas_fixture/graph?limit=0")
    assert res_zero.status_code == 422

    res_neg = client.get("/api/v1/repositories/repo::atlas_fixture/graph?limit=-5")
    assert res_neg.status_code == 422

    res_str = client.get("/api/v1/repositories/repo::atlas_fixture/graph?limit=abc")
    assert res_str.status_code == 422


def test_duplicate_edges_generate_deterministic_ids_regardless_of_input_order():
    """Verify identical duplicate edges receive deterministic IDs regardless of input arrival order."""
    repo = Repository(id="repo::test", name="test", source="local")
    fn1 = Function.create(repo_id="repo::test", name="f1", qualified_name="f1", file_path="app.py", start_line=1, end_line=5, start_byte=0, end_byte=50)
    fn2 = Function.create(repo_id="repo::test", name="f2", qualified_name="f2", file_path="app.py", start_line=10, end_line=15, start_byte=60, end_byte=100)

    # Two duplicate CALLS edges with identical source, target, and location
    edge1 = Relationship(rel_type=RelationshipType.CALLS, source_id=fn1.id, target_id=fn2.id)
    edge2 = Relationship(rel_type=RelationshipType.CALLS, source_id=fn1.id, target_id=fn2.id)

    ucm_order1 = UnifiedCodeModel(repository=repo)
    ucm_order1.add_function(fn1)
    ucm_order1.add_function(fn2)
    ucm_order1.add_relationship(edge1)
    ucm_order1.add_relationship(edge2)

    ucm_order2 = UnifiedCodeModel(repository=repo)
    ucm_order2.add_function(fn1)
    ucm_order2.add_function(fn2)
    ucm_order2.add_relationship(edge2)
    ucm_order2.add_relationship(edge1)

    _, edges1 = serialize_ucm_graph(ucm_order1)
    _, edges2 = serialize_ucm_graph(ucm_order2)

    assert len(edges1) == 2
    assert len(edges2) == 2
    assert [e.id for e in edges1] == [e.id for e in edges2]
    assert edges1[0].id == f"{fn1.id}->CALLS->{fn2.id}"
    assert edges1[1].id == f"{fn1.id}->CALLS->{fn2.id}#1"


# ==============================================================================
# 7. End-to-End Simulation of GraphRetriever Records
# ==============================================================================


def test_get_repository_graph_from_simulated_database_records(
    resolved_fixture_ucm: UnifiedCodeModel,
):
    """Verify endpoint calls real GraphRetriever query translation and model serialization."""
    repo_id = resolved_fixture_ucm.repository.id

    repo_record = {"props": resolved_fixture_ucm.repository.to_dict()}
    file_records = [{"props": f.to_dict()} for f in resolved_fixture_ucm.files]
    module_records = [{"props": m.to_dict()} for m in resolved_fixture_ucm.modules]
    class_records = [{"props": c.to_dict()} for c in resolved_fixture_ucm.classes]
    func_records = [{"props": fn.to_dict()} for fn in resolved_fixture_ucm.functions]
    meth_records = [{"props": mt.to_dict()} for mt in resolved_fixture_ucm.methods]
    import_records = [{"props": im.to_dict()} for im in resolved_fixture_ucm.imports]

    rel_records = []
    for r in resolved_fixture_ucm.relationships:
        props = {}
        if r.location:
            props.update(
                {
                    "start_line": r.location.start_point.line,
                    "start_column": r.location.start_point.column,
                    "end_line": r.location.end_point.line,
                    "end_column": r.location.end_point.column,
                    "start_byte": r.location.start_byte,
                    "end_byte": r.location.end_byte,
                }
            )
        props.update(r.metadata)
        rel_records.append(
            {
                "source_id": r.source_id,
                "target_id": r.target_id,
                "rel_type": r.rel_type.value,
                "properties": props,
            }
        )

    mock_session = MagicMock(spec=Session)

    def mock_fixture_run(query: str, **kwargs):
        res = MagicMock()
        if "MATCH (r:Repository" in query:
            res.single.return_value = repo_record
        elif "MATCH (n:File" in query:
            res.__iter__.return_value = file_records
        elif "MATCH (n:Module" in query:
            res.__iter__.return_value = module_records
        elif "MATCH (n:Class" in query:
            res.__iter__.return_value = class_records
        elif "MATCH (n:Function" in query:
            res.__iter__.return_value = func_records
        elif "MATCH (n:Method" in query:
            res.__iter__.return_value = meth_records
        elif "MATCH (n:Import" in query:
            res.__iter__.return_value = import_records
        elif "MATCH (src)-[r]->(tgt)" in query:
            res.__iter__.return_value = rel_records
        else:
            res.__iter__.return_value = []
            res.single.return_value = None
        return res

    mock_session.run.side_effect = mock_fixture_run

    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(f"/api/v1/repositories/{repo_id}/graph")

    assert response.status_code == 200
    data = response.json()
    assert data["repository_id"] == repo_id
    assert len(data["nodes"]) == 53
    assert len(data["relationships"]) == 58


def test_neo4j_driver_uninitialized_returns_503():
    """Verify endpoint returns 503 when the application driver is not initialized."""
    set_driver(None)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/v1/repositories/repo::demo/graph")
    assert response.status_code == 503
    assert response.json()["detail"] == "Database service unavailable"


def test_get_repository_graph_endpoint_with_neo4j_records(
    resolved_fixture_ucm: UnifiedCodeModel,
):
    """Regression test: verify API returns HTTP 200 with 53 nodes and 58 relationships
    when Neo4j driver returns neo4j.Record instances where ('props' in record) is False.
    """
    repo_id = resolved_fixture_ucm.repository.id

    repo_rec = Record([("props", resolved_fixture_ucm.repository.to_dict())])
    file_recs = [Record([("props", f.to_dict())]) for f in resolved_fixture_ucm.files]
    module_recs = [Record([("props", m.to_dict())]) for m in resolved_fixture_ucm.modules]
    class_recs = [Record([("props", c.to_dict())]) for c in resolved_fixture_ucm.classes]
    func_recs = [Record([("props", fn.to_dict())]) for fn in resolved_fixture_ucm.functions]
    meth_recs = [Record([("props", mt.to_dict())]) for mt in resolved_fixture_ucm.methods]
    import_recs = [Record([("props", im.to_dict())]) for im in resolved_fixture_ucm.imports]

    rel_recs = []
    for r in resolved_fixture_ucm.relationships:
        props = {}
        if r.location:
            props.update(
                {
                    "start_line": r.location.start_point.line,
                    "start_column": r.location.start_point.column,
                    "end_line": r.location.end_point.line,
                    "end_column": r.location.end_point.column,
                    "start_byte": r.location.start_byte,
                    "end_byte": r.location.end_byte,
                }
            )
        props.update(r.metadata)
        rel_recs.append(
            Record(
                [
                    ("source_id", r.source_id),
                    ("target_id", r.target_id),
                    ("rel_type", r.rel_type.value),
                    ("properties", props),
                ]
            )
        )

    mock_session = MagicMock(spec=Session)

    def mock_run(query: str, **kwargs):
        res = MagicMock()
        if "MATCH (r:Repository" in query:
            res.single.return_value = repo_rec
        elif "MATCH (n:File" in query:
            res.__iter__.return_value = file_recs
        elif "MATCH (n:Module" in query:
            res.__iter__.return_value = module_recs
        elif "MATCH (n:Class" in query:
            res.__iter__.return_value = class_recs
        elif "MATCH (n:Function" in query:
            res.__iter__.return_value = func_recs
        elif "MATCH (n:Method" in query:
            res.__iter__.return_value = meth_recs
        elif "MATCH (n:Import" in query:
            res.__iter__.return_value = import_recs
        elif "MATCH (src)-[r]->(tgt)" in query:
            res.__iter__.return_value = rel_recs
        else:
            res.__iter__.return_value = []
            res.single.return_value = None
        return res

    mock_session.run.side_effect = mock_run

    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    # Test URL encoded repo ID
    response = client.get(f"/api/v1/repositories/repo%3A%3Aatlas_fixture/graph")

    assert response.status_code == 200
    data = response.json()
    assert data["repository_id"] == "repo::atlas_fixture"
    assert len(data["nodes"]) == 53
    assert len(data["relationships"]) == 58


