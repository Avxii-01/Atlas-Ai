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


# ==============================================================================
# 5. Bounded Repository Overview Tests (GET /graph?view=overview)
# ==============================================================================


def _build_mock_overview_record(
    repo: Repository,
    files: list[File],
    offset: int = 0,
    limit: int = 50,
) -> Record:
    """Helper constructing a mock Neo4j Record simulating get_repository_overview Cypher output."""
    total_files = len(files)
    sorted_files = sorted(files, key=lambda f: f.path)
    paged_files = sorted_files[offset : offset + limit]

    file_props = [f.to_dict() for f in paged_files]
    edge_dicts = [
        {
            "source_id": repo.id,
            "target_id": f.id,
            "rel_type": "CONTAINS",
            "properties": {},
        }
        for f in paged_files
    ]

    return Record(
        [
            ("repo_props", repo.to_dict()),
            ("total_files", total_files),
            ("files", file_props),
            ("edges", edge_dicts),
        ]
    )


def test_overview_small_repository_returns_root_and_files_only(
    resolved_fixture_ucm: UnifiedCodeModel,
):
    """Verify overview returns exactly 1 Repository node, File nodes, CONTAINS edges only, and valid metadata."""
    repo = resolved_fixture_ucm.repository
    files = resolved_fixture_ucm.files
    repo_id = repo.id

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_overview_record(repo, files, offset=0, limit=50)

    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(f"/api/v1/repositories/{repo_id}/graph?view=overview")

    assert response.status_code == 200
    data = response.json()

    assert data["repository_id"] == repo_id
    assert len(data["nodes"]) == 1 + len(files)  # 1 repo + 7 files = 8
    assert len(data["relationships"]) == len(files)  # 7 edges

    # Verify strictly only Repository and File labels exist
    node_labels = {n["label"] for n in data["nodes"]}
    assert node_labels == {"Repository", "File"}
    assert data["nodes"][0]["label"] == "Repository"
    assert data["nodes"][0]["id"] == repo_id

    # Verify strictly only CONTAINS relationships exist
    rel_types = {r["type"] for r in data["relationships"]}
    assert rel_types == {"CONTAINS"}

    # Verify metadata fields
    assert "metadata" in data and data["metadata"] is not None
    meta = data["metadata"]
    assert meta["view"] == "overview"
    assert meta["total_files"] == 7
    assert meta["returned_files"] == 7
    assert meta["has_more"] is False
    assert meta["truncated"] is False
    assert meta["offset"] == 0
    assert meta["limit"] == 50

    # Verify zero duplicate node IDs or edge IDs
    node_ids = [n["id"] for n in data["nodes"]]
    assert len(node_ids) == len(set(node_ids))
    edge_ids = [r["id"] for r in data["relationships"]]
    assert len(edge_ids) == len(set(edge_ids))

    # Verify endpoint presence invariant
    valid_ids = set(node_ids)
    for edge in data["relationships"]:
        assert edge["source"] in valid_ids
        assert edge["target"] in valid_ids


def test_overview_pagination_and_truncation(resolved_fixture_ucm: UnifiedCodeModel):
    """Verify overview pagination with limit and offset slices files deterministically and updates metadata."""
    repo = resolved_fixture_ucm.repository
    files = resolved_fixture_ucm.files
    repo_id = repo.id

    mock_session = MagicMock(spec=Session)

    def mock_run(cypher, **params):
        offset = params.get("offset", 0)
        limit = params.get("limit", 50)
        res = MagicMock()
        res.single.return_value = _build_mock_overview_record(repo, files, offset=offset, limit=limit)
        return res

    mock_session.run.side_effect = mock_run

    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)

    # Page 1: limit=2, offset=0
    resp1 = client.get(f"/api/v1/repositories/{repo_id}/graph?view=overview&limit=2&offset=0")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1["nodes"]) == 3  # 1 repo + 2 files
    assert len(data1["relationships"]) == 2
    assert data1["metadata"]["total_files"] == 7
    assert data1["metadata"]["returned_files"] == 2
    assert data1["metadata"]["has_more"] is True
    assert data1["metadata"]["truncated"] is True
    page1_file_ids = {n["id"] for n in data1["nodes"] if n["label"] == "File"}

    # Page 2: limit=2, offset=2
    resp2 = client.get(f"/api/v1/repositories/{repo_id}/graph?view=overview&limit=2&offset=2")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["nodes"]) == 3
    page2_file_ids = {n["id"] for n in data2["nodes"] if n["label"] == "File"}
    # Disjoint check
    assert page1_file_ids.isdisjoint(page2_file_ids)

    # Page 4: limit=2, offset=6 (last file)
    resp4 = client.get(f"/api/v1/repositories/{repo_id}/graph?view=overview&limit=2&offset=6")
    assert resp4.status_code == 200
    data4 = resp4.json()
    assert len(data4["nodes"]) == 2  # 1 repo + 1 file
    assert data4["metadata"]["returned_files"] == 1
    assert data4["metadata"]["has_more"] is False
    assert data4["metadata"]["truncated"] is True

    # Offset beyond end: limit=2, offset=10
    resp_empty = client.get(f"/api/v1/repositories/{repo_id}/graph?view=overview&limit=2&offset=10")
    assert resp_empty.status_code == 200
    data_empty = resp_empty.json()
    assert len(data_empty["nodes"]) == 1  # Repository root only
    assert len(data_empty["relationships"]) == 0
    assert data_empty["metadata"]["returned_files"] == 0
    assert data_empty["metadata"]["has_more"] is False
    assert data_empty["metadata"]["truncated"] is True


def test_overview_root_does_not_count_toward_limit(resolved_fixture_ucm: UnifiedCodeModel):
    """Verify limit strictly applies to File nodes and root Repository node does not consume budget."""
    repo = resolved_fixture_ucm.repository
    files = resolved_fixture_ucm.files
    repo_id = repo.id

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_overview_record(repo, files, offset=0, limit=1)

    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/api/v1/repositories/{repo_id}/graph?view=overview&limit=1")
    assert resp.status_code == 200
    data = resp.json()

    # limit=1 must return 1 File node PLUS the Repository root = 2 nodes total
    assert len(data["nodes"]) == 2
    assert data["nodes"][0]["label"] == "Repository"
    assert data["nodes"][1]["label"] == "File"
    assert len(data["relationships"]) == 1
    assert data["metadata"]["returned_files"] == 1


def test_overview_deterministic_ordering_across_repeated_calls(resolved_fixture_ucm: UnifiedCodeModel):
    """Verify multiple overview calls return identical deterministic ordering of nodes and edges."""
    repo = resolved_fixture_ucm.repository
    files = resolved_fixture_ucm.files
    repo_id = repo.id

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_overview_record(repo, files, offset=0, limit=50)

    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resps = [client.get(f"/api/v1/repositories/{repo_id}/graph?view=overview") for _ in range(3)]

    assert all(r.status_code == 200 for r in resps)
    payloads = [r.json() for r in resps]

    for p in payloads[1:]:
        assert [n["id"] for n in p["nodes"]] == [n["id"] for n in payloads[0]["nodes"]]
        assert [r["id"] for r in p["relationships"]] == [r["id"] for r in payloads[0]["relationships"]]


def test_overview_empty_repository_returns_root_only():
    """Verify overview of a repository with 0 files returns HTTP 200, 1 root node, 0 edges, and clean metadata."""
    repo = Repository(id="repo::empty", name="empty", source="local")

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = Record(
        [
            ("repo_props", repo.to_dict()),
            ("total_files", 0),
            ("files", []),
            ("edges", []),
        ]
    )

    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::empty/graph?view=overview")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["label"] == "Repository"
    assert data["relationships"] == []
    assert data["metadata"]["total_files"] == 0
    assert data["metadata"]["returned_files"] == 0
    assert data["metadata"]["has_more"] is False
    assert data["metadata"]["truncated"] is False


def test_overview_missing_repository_returns_404():
    """Verify overview of a nonexistent repository returns HTTP 404."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = None

    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::nonexistent/graph?view=overview")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_overview_invalid_parameters():
    """Verify overview rejects invalid view names, limit > 200, limit < 1, and offset < 0."""
    client = TestClient(app, raise_server_exceptions=False)

    # Invalid view name -> 400
    res_view = client.get("/api/v1/repositories/repo::demo/graph?view=invalid_view")
    assert res_view.status_code == 400
    assert "invalid view" in res_view.json()["detail"].lower()

    # Limit > 200 -> 400
    res_limit_high = client.get("/api/v1/repositories/repo::demo/graph?view=overview&limit=201")
    assert res_limit_high.status_code == 400
    assert "cannot exceed 200" in res_limit_high.json()["detail"].lower()

    # Limit < 1 -> 422
    res_limit_low = client.get("/api/v1/repositories/repo::demo/graph?view=overview&limit=0")
    assert res_limit_low.status_code == 422

    # Offset < 0 -> 422
    res_offset_neg = client.get("/api/v1/repositories/repo::demo/graph?view=overview&offset=-1")
    assert res_offset_neg.status_code == 422


def test_overview_does_not_invoke_full_graph_reconstruction(resolved_fixture_ucm: UnifiedCodeModel):
    """Verify overview path strictly uses GraphRetriever.get_repository_overview and does NOT call get_repository_graph."""
    repo = resolved_fixture_ucm.repository
    files = resolved_fixture_ucm.files
    repo_id = repo.id

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_overview_record(repo, files, offset=0, limit=50)

    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)

    with patch.object(GraphRetriever, "get_repository_graph") as mock_full_graph:
        resp = client.get(f"/api/v1/repositories/{repo_id}/graph?view=overview")
        assert resp.status_code == 200
        # Prove get_repository_graph was never invoked
        mock_full_graph.assert_not_called()


def test_overview_preserves_full_graph_compatibility_when_view_omitted(
    client: TestClient,
    resolved_fixture_ucm: UnifiedCodeModel,
):
    """Verify backward compatibility: when view is omitted, the full graph is reconstructed with metadata=None."""
    repo_id = resolved_fixture_ucm.repository.id

    with patch.object(GraphRetriever, "get_repository_graph", return_value=resolved_fixture_ucm):
        resp = client.get(f"/api/v1/repositories/{repo_id}/graph")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) == 53
    assert len(data["relationships"]) == 58
    assert data["metadata"] is None


def test_overview_database_unavailable_returns_503():
    """Verify overview returns 503 when Neo4j is unreachable."""
    set_driver(None)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/graph?view=overview")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Database service unavailable"


def test_overview_cross_repository_isolation():
    """Verify overview Cypher strictly scopes queries to the requested repo_id and cannot return other repositories."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = Record(
        [
            ("repo_props", {"id": "repo::isolated", "name": "isolated", "source": "/iso"}),
            ("total_files", 1),
            ("files", [{"id": "repo::isolated::file::mod.py", "repo_id": "repo::isolated", "path": "mod.py", "language": "python", "start_line": 1, "end_line": 10}]),
            ("edges", [{"source_id": "repo::isolated", "target_id": "repo::isolated::file::mod.py", "rel_type": "CONTAINS", "properties": {}}]),
        ]
    )

    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::isolated/graph?view=overview")
    assert resp.status_code == 200

    # Inspect call args to prove $repo_id was passed to Cypher
    call_params = mock_session.run.call_args[1]
    assert call_params["repo_id"] == "repo::isolated"


def test_legacy_graph_with_nodes_exceeding_overview_maximum_returns_full_graph():
    """Verify legacy route without view returns all nodes (>200) without overview truncation or caps."""
    repo = Repository(id="repo::large", name="large", source="local")
    ucm = UnifiedCodeModel(repository=repo)
    # Add 125 files and 124 functions -> 1 + 125 + 124 = 250 nodes (exceeds overview max of 200)
    for i in range(125):
        f = File(
            id=f"repo::large::file::f{i:03d}.py",
            repo_id="repo::large",
            path=f"f{i:03d}.py",
            language="python",
            start_line=1,
            end_line=10,
        )
        ucm.add_file(f)
        ucm.add_relationship(
            Relationship(
                source_id="repo::large",
                target_id=f.id,
                rel_type=RelationshipType.CONTAINS,
            )
        )
    for j in range(124):
        fn = Function(
            id=f"repo::large::file::f000.py::fn{j:03d}",
            repo_id="repo::large",
            name=f"fn{j:03d}",
            qualified_name=f"f000.fn{j:03d}",
            file_path="f000.py",
            language="python",
            start_line=j + 1,
            end_line=j + 2,
            start_byte=0,
            end_byte=10,
        )
        ucm.add_function(fn)
        ucm.add_relationship(
            Relationship(
                source_id="repo::large::file::f000.py",
                target_id=fn.id,
                rel_type=RelationshipType.CONTAINS,
            )
        )

    # 1. Without view and without limit: returns all 250 nodes (> 200 overview limit) and metadata is None
    with patch.object(GraphRetriever, "get_repository_graph", return_value=ucm):
        mock_driver = MagicMock(spec=Driver)
        set_driver(mock_driver)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/repositories/repo::large/graph")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) == 250
    assert len(data["relationships"]) == 249
    assert data["metadata"] is None

    # 2. Without view with explicit limit=220 (> 200 overview maximum):
    with patch.object(GraphRetriever, "get_repository_graph", return_value=ucm):
        resp_limit = client.get("/api/v1/repositories/repo::large/graph?limit=220")

    assert resp_limit.status_code == 200
    data_limit = resp_limit.json()
    assert len(data_limit["nodes"]) == 220
    assert data_limit["metadata"] is None


def test_response_schema_compatibility_between_legacy_and_overview(resolved_fixture_ucm: UnifiedCodeModel):
    """Verify that both legacy and overview routes emit identical NodeModel and RelationshipModel schema keys."""
    repo = resolved_fixture_ucm.repository
    files = resolved_fixture_ucm.files
    repo_id = repo.id

    # Overview call
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_overview_record(repo, files, offset=0, limit=50)
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    overview_resp = client.get(f"/api/v1/repositories/{repo_id}/graph?view=overview")
    assert overview_resp.status_code == 200
    overview_data = overview_resp.json()

    # Legacy call
    with patch.object(GraphRetriever, "get_repository_graph", return_value=resolved_fixture_ucm):
        legacy_resp = client.get(f"/api/v1/repositories/{repo_id}/graph")
    assert legacy_resp.status_code == 200
    legacy_data = legacy_resp.json()

    # Required node keys per NodeModel: id, label, name, type, display_name, properties
    expected_node_keys = {"id", "label", "name", "type", "display_name", "properties"}
    for node in legacy_data["nodes"]:
        assert set(node.keys()) == expected_node_keys
    for node in overview_data["nodes"]:
        assert set(node.keys()) == expected_node_keys

    # Required relationship keys per RelationshipModel
    expected_rel_keys = {"id", "source", "target", "type", "source_id", "target_id", "rel_type", "properties", "metadata"}
    for edge in legacy_data["relationships"]:
        assert set(edge.keys()) == expected_rel_keys
    for edge in overview_data["relationships"]:
        assert set(edge.keys()) == expected_rel_keys

    # Top-level keys:
    assert set(legacy_data.keys()) == {"repository_id", "nodes", "relationships", "metadata"}
    assert legacy_data["metadata"] is None

    assert set(overview_data.keys()) == {"repository_id", "nodes", "relationships", "metadata"}
    assert overview_data["metadata"] is not None
    expected_metadata_keys = {"view", "total_files", "returned_files", "has_more", "truncated", "offset", "limit"}
    assert set(overview_data["metadata"].keys()) == expected_metadata_keys


def _build_mock_children_record(
    parent_props: dict,
    parent_label: str,
    children_props_list: list[dict],
    children_labels_list: list[list[str]],
    offset: int = 0,
    limit: int = 50,
    repo_exists: bool = True,
) -> Record:
    total_children = len(children_props_list)
    paged_props = children_props_list[offset : offset + limit]
    paged_labels = children_labels_list[offset : offset + limit]
    edges = [
        {
            "source_id": parent_props["id"],
            "target_id": c["id"],
            "rel_type": "CONTAINS",
            "properties": {},
        }
        for c in paged_props
    ]
    return Record(
        [
            ("repo_exists", repo_exists),
            ("parent_props", parent_props if repo_exists else None),
            ("parent_labels", [parent_label] if repo_exists and parent_props else []),
            ("total_children", total_children if repo_exists and parent_props else 0),
            ("children_props", paged_props if repo_exists and parent_props else []),
            ("children_labels", paged_labels if repo_exists and parent_props else []),
            ("edges", edges if repo_exists and parent_props else []),
        ]
    )


def test_children_parent_with_multiple_direct_children():
    """Verify expanding an entity with multiple children returns parent, children, edges, and metadata."""
    parent_props = {
        "id": "repo::demo::file::models.py",
        "repo_id": "repo::demo",
        "path": "models.py",
        "language": "python",
        "start_line": 1,
        "end_line": 50,
    }
    children_props = [
        {
            "id": "repo::demo::class::Item",
            "repo_id": "repo::demo",
            "name": "Item",
            "qualified_name": "models.Item",
            "file_path": "models.py",
            "language": "python",
            "start_line": 5,
            "end_line": 25,
            "start_byte": 50,
            "end_byte": 250,
        },
        {
            "id": "repo::demo::function::make_item",
            "repo_id": "repo::demo",
            "name": "make_item",
            "qualified_name": "models.make_item",
            "file_path": "models.py",
            "language": "python",
            "start_line": 30,
            "end_line": 45,
            "start_byte": 300,
            "end_byte": 450,
        },
    ]
    children_labels = [["Class"], ["Function"]]

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_children_record(
        parent_props, "File", children_props, children_labels
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::file::models.py/children")

    assert resp.status_code == 200
    data = resp.json()
    assert data["repository_id"] == "repo::demo"
    assert data["parent_id"] == "repo::demo::file::models.py"
    assert data["parent"]["id"] == "repo::demo::file::models.py"
    assert data["parent"]["label"] == "File"
    assert len(data["children"]) == 2
    assert data["children"][0]["id"] == "repo::demo::class::Item"
    assert data["children"][0]["label"] == "Class"
    assert data["children"][1]["id"] == "repo::demo::function::make_item"
    assert data["children"][1]["label"] == "Function"
    assert len(data["relationships"]) == 2
    assert data["relationships"][0]["type"] == "CONTAINS"
    assert data["total_children"] == 2
    assert data["returned_children"] == 2
    assert data["has_more"] is False
    assert data["truncated"] is False
    assert data["offset"] == 0
    assert data["limit"] == 50


def test_children_parent_with_no_children():
    """Verify expanding an entity with no direct children (e.g. Method) returns 200 and empty lists."""
    parent_props = {
        "id": "repo::demo::method::Item.save",
        "repo_id": "repo::demo",
        "name": "save",
        "qualified_name": "models.Item.save",
        "file_path": "models.py",
        "language": "python",
        "start_line": 15,
        "end_line": 20,
        "start_byte": 150,
        "end_byte": 200,
    }
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_children_record(
        parent_props, "Method", [], []
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::method::Item.save/children")

    assert resp.status_code == 200
    data = resp.json()
    assert data["parent"]["id"] == "repo::demo::method::Item.save"
    assert data["parent"]["label"] == "Method"
    assert data["children"] == []
    assert data["relationships"] == []
    assert data["total_children"] == 0
    assert data["returned_children"] == 0
    assert data["has_more"] is False
    assert data["truncated"] is False


def test_children_pagination_across_multiple_pages():
    """Verify children pagination across pages with limit and offset."""
    parent_props = {
        "id": "repo::demo::file::big.py",
        "repo_id": "repo::demo",
        "path": "big.py",
        "language": "python",
        "start_line": 1,
        "end_line": 100,
    }
    children_props = [
        {
            "id": f"repo::demo::function::fn_{i}",
            "repo_id": "repo::demo",
            "name": f"fn_{i}",
            "qualified_name": f"big.fn_{i}",
            "file_path": "big.py",
            "language": "python",
            "start_line": i * 10 + 1,
            "end_line": i * 10 + 5,
            "start_byte": i * 100,
            "end_byte": i * 100 + 50,
        }
        for i in range(5)
    ]
    children_labels = [["Function"] for _ in range(5)]

    mock_session = MagicMock(spec=Session)

    def mock_run_paging(query, **params):
        offset = params.get("offset", 0)
        limit = params.get("limit", 50)
        res = MagicMock()
        res.single.return_value = _build_mock_children_record(
            parent_props, "File", children_props, children_labels, offset=offset, limit=limit
        )
        return res

    mock_session.run.side_effect = mock_run_paging
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)

    # Page 1: limit=2, offset=0
    resp1 = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::file::big.py/children?limit=2&offset=0")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1["children"]) == 2
    assert data1["children"][0]["id"] == "repo::demo::function::fn_0"
    assert data1["children"][1]["id"] == "repo::demo::function::fn_1"
    assert data1["total_children"] == 5
    assert data1["returned_children"] == 2
    assert data1["has_more"] is True
    assert data1["truncated"] is True

    # Page 2: limit=2, offset=2
    resp2 = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::file::big.py/children?limit=2&offset=2")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["children"]) == 2
    assert data2["children"][0]["id"] == "repo::demo::function::fn_2"
    assert data2["children"][1]["id"] == "repo::demo::function::fn_3"
    assert data2["has_more"] is True

    # Page 3: limit=2, offset=4 (last element)
    resp3 = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::file::big.py/children?limit=2&offset=4")
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert len(data3["children"]) == 1
    assert data3["children"][0]["id"] == "repo::demo::function::fn_4"
    assert data3["has_more"] is False
    assert data3["truncated"] is True

    # Offset beyond total
    resp_empty = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::file::big.py/children?limit=2&offset=10")
    assert resp_empty.status_code == 200
    data_empty = resp_empty.json()
    assert len(data_empty["children"]) == 0
    assert data_empty["has_more"] is False


def test_children_deterministic_ordering():
    """Verify multiple children calls return identical deterministic ordering of nodes and edges."""
    parent_props = {
        "id": "repo::demo::file::models.py",
        "repo_id": "repo::demo",
        "path": "models.py",
        "language": "python",
        "start_line": 1,
        "end_line": 50,
    }
    children_props = [
        {
            "id": f"repo::demo::function::fn_{i}",
            "repo_id": "repo::demo",
            "name": f"fn_{i}",
            "qualified_name": f"models.fn_{i}",
            "file_path": "models.py",
            "language": "python",
            "start_line": i * 10 + 1,
            "end_line": i * 10 + 5,
            "start_byte": i * 100,
            "end_byte": i * 100 + 50,
        }
        for i in [3, 1, 4, 0, 2]
    ]
    children_labels = [["Function"] for _ in range(5)]

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_children_record(
        parent_props, "File", children_props, children_labels
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resps = [
        client.get("/api/v1/repositories/repo::demo/entities/repo::demo::file::models.py/children")
        for _ in range(3)
    ]
    assert all(r.status_code == 200 for r in resps)
    payloads = [r.json() for r in resps]

    for p in payloads[1:]:
        assert [c["id"] for c in p["children"]] == [c["id"] for c in payloads[0]["children"]]
        assert [r["id"] for r in p["relationships"]] == [r["id"] for r in payloads[0]["relationships"]]


def test_children_limit_validation_and_maximum_enforcement():
    """Verify children endpoint validates limit and offset boundaries."""
    client = TestClient(app, raise_server_exceptions=False)

    # limit > 200 -> 422 (FastAPI Query le=200 validation)
    res_high = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::file::a.py/children?limit=201")
    assert res_high.status_code == 422

    # limit < 1 -> 422 (FastAPI Query ge=1 validation)
    res_low = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::file::a.py/children?limit=0")
    assert res_low.status_code == 422

    # offset < 0 -> 422 (FastAPI Query ge=0 validation)
    res_neg_offset = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::file::a.py/children?offset=-1")
    assert res_neg_offset.status_code == 422

    # Direct service boundary validation
    service = RepositoryService()
    with pytest.raises(Exception) as exc_info:
        service.get_entity_children("repo::demo", "file::a.py", limit=201)
    assert "cannot exceed 200" in str(exc_info.value)

    with pytest.raises(Exception) as exc_info2:
        service.get_entity_children("repo::demo", "file::a.py", limit=0)
    assert "Limit must be >= 1" in str(exc_info2.value)


def test_children_missing_repository_returns_404():
    """Verify children of a nonexistent repository returns HTTP 404."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = Record(
        [
            ("repo_exists", False),
            ("parent_props", None),
            ("parent_labels", []),
            ("total_children", 0),
            ("children_props", []),
            ("children_labels", []),
            ("edges", []),
        ]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::nonexistent/entities/file::a.py/children")
    assert resp.status_code == 404
    assert "Repository 'repo::nonexistent' not found" in resp.json()["detail"]


def test_children_missing_entity_returns_404():
    """Verify expanding an entity that does not exist in the repository returns HTTP 404."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = Record(
        [
            ("repo_exists", True),
            ("parent_props", None),
            ("parent_labels", []),
            ("total_children", 0),
            ("children_props", []),
            ("children_labels", []),
            ("edges", []),
        ]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/file::nonexistent.py/children")
    assert resp.status_code == 404
    assert "Entity 'file::nonexistent.py' not found in repository 'repo::demo'" in resp.json()["detail"]


def test_children_entity_belonging_to_different_repository_returns_404():
    """Verify requesting an entity belonging to a different repository returns HTTP 404."""
    mock_session = MagicMock(spec=Session)
    # The Cypher query isolates by repo_id, so a different repo's entity returns parent_props=None
    mock_session.run.return_value.single.return_value = Record(
        [
            ("repo_exists", True),
            ("parent_props", None),
            ("parent_labels", []),
            ("total_children", 0),
            ("children_props", []),
            ("children_labels", []),
            ("edges", []),
        ]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::repo_a/entities/repo::repo_b::file::secret.py/children")
    assert resp.status_code == 404
    assert "Entity 'repo::repo_b::file::secret.py' not found in repository 'repo::repo_a'" in resp.json()["detail"]


def test_children_returns_only_direct_contains_not_transitive():
    """Verify expanding an entity returns only its immediate direct CONTAINS children, not transitive descendants."""
    file_parent = {
        "id": "repo::demo::file::app.py",
        "repo_id": "repo::demo",
        "path": "app.py",
        "language": "python",
        "start_line": 1,
        "end_line": 50,
    }
    # File directly contains Class, but NOT Method (Method is contained in Class)
    direct_class_child = {
        "id": "repo::demo::class::Service",
        "repo_id": "repo::demo",
        "name": "Service",
        "qualified_name": "app.Service",
        "file_path": "app.py",
        "language": "python",
        "start_line": 10,
        "end_line": 40,
        "start_byte": 100,
        "end_byte": 400,
    }

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_children_record(
        file_parent, "File", [direct_class_child], [["Class"]]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::file::app.py/children")
    assert resp.status_code == 200
    data = resp.json()

    # Must contain Class, but must not contain any nested method
    assert len(data["children"]) == 1
    assert data["children"][0]["id"] == "repo::demo::class::Service"
    assert data["children"][0]["label"] == "Class"


def test_children_endpoint_presence_invariant():
    """Verify all returned relationships strictly connect parent to returned child nodes."""
    parent_props = {
        "id": "repo::demo::file::a.py",
        "repo_id": "repo::demo",
        "path": "a.py",
        "language": "python",
        "start_line": 1,
        "end_line": 30,
    }
    children_props = [
        {
            "id": "repo::demo::function::foo",
            "repo_id": "repo::demo",
            "name": "foo",
            "qualified_name": "a.foo",
            "file_path": "a.py",
            "language": "python",
            "start_line": 5,
            "end_line": 15,
            "start_byte": 50,
            "end_byte": 150,
        }
    ]
    # Edge connecting parent to child + a dangling edge that should be filtered out
    edges = [
        {
            "source_id": "repo::demo::file::a.py",
            "target_id": "repo::demo::function::foo",
            "rel_type": "CONTAINS",
            "properties": {},
        },
        {
            "source_id": "repo::demo::file::a.py",
            "target_id": "repo::demo::function::dangling",
            "rel_type": "CONTAINS",
            "properties": {},
        },
    ]

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = Record(
        [
            ("repo_exists", True),
            ("parent_props", parent_props),
            ("parent_labels", ["File"]),
            ("total_children", 1),
            ("children_props", children_props),
            ("children_labels", [["Function"]]),
            ("edges", edges),
        ]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::file::a.py/children")
    assert resp.status_code == 200
    data = resp.json()

    valid_ids = {data["parent"]["id"]} | {c["id"] for c in data["children"]}
    assert len(data["relationships"]) == 1
    for rel in data["relationships"]:
        assert rel["source"] in valid_ids
        assert rel["target"] in valid_ids


def test_children_does_not_invoke_full_graph_reconstruction():
    """Verify child expansion does not invoke full graph reconstruction (GraphRetriever.get_repository_graph)."""
    parent_props = {
        "id": "repo::demo::file::a.py",
        "repo_id": "repo::demo",
        "path": "a.py",
        "language": "python",
        "start_line": 1,
        "end_line": 30,
    }
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_children_record(
        parent_props, "File", [], []
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    with patch.object(GraphRetriever, "get_repository_graph") as mock_full:
        resp = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::file::a.py/children")
        assert resp.status_code == 200
        mock_full.assert_not_called()


def test_children_database_unavailable_returns_503():
    """Verify child expansion returns 503 when Neo4j is unreachable."""
    set_driver(None)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::file::a.py/children")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Database service unavailable"


def _build_mock_neighbors_record(
    center_props: dict,
    center_label: str,
    edges: list[dict],
    neighbor_props_list: list[dict],
    neighbor_labels_list: list[list[str]],
    offset: int = 0,
    limit: int = 50,
    repo_exists: bool = True,
) -> Record:
    total_relationships = len(edges)
    paged_edges = edges[offset : offset + limit]
    paged_edge_endpoints = {e["source_id"] for e in paged_edges} | {e["target_id"] for e in paged_edges}
    paged_nbr_props = [p for p in neighbor_props_list if p["id"] in paged_edge_endpoints and p["id"] != center_props["id"]]
    paged_nbr_labels = [l for p, l in zip(neighbor_props_list, neighbor_labels_list) if p["id"] in paged_edge_endpoints and p["id"] != center_props["id"]]
    total_neighbors = len([p for p in neighbor_props_list if p["id"] != center_props["id"]])

    return Record(
        [
            ("repo_exists", repo_exists),
            ("center_props", center_props if repo_exists else None),
            ("center_labels", [center_label] if repo_exists and center_props else []),
            ("total_relationships", total_relationships if repo_exists and center_props else 0),
            ("total_neighbors", total_neighbors if repo_exists and center_props else 0),
            ("edges", paged_edges if repo_exists and center_props else []),
            ("neighbor_props", paged_nbr_props if repo_exists and center_props else []),
            ("neighbor_labels", paged_nbr_labels if repo_exists and center_props else []),
        ]
    )


def test_neighbors_incoming_relationship_selection():
    """Verify direction=incoming returns relationships whose target is the center entity."""
    center_props = {
        "id": "repo::demo::class::Item",
        "repo_id": "repo::demo",
        "name": "Item",
        "qualified_name": "models.Item",
        "file_path": "models.py",
        "language": "python",
        "start_line": 6,
        "end_line": 20,
        "start_byte": 50,
        "end_byte": 200,
    }
    file_props = {
        "id": "repo::demo::file::models.py",
        "repo_id": "repo::demo",
        "path": "models.py",
        "language": "python",
        "start_line": 1,
        "end_line": 50,
        "start_byte": 0,
        "end_byte": 500,
    }
    # Incoming CONTAINS edge: File -> Item
    edges = [
        {
            "source_id": "repo::demo::file::models.py",
            "target_id": "repo::demo::class::Item",
            "rel_type": "CONTAINS",
            "properties": {},
        }
    ]

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_neighbors_record(
        center_props, "Class", edges, [file_props], [["File"]]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::class::Item/neighbors?direction=incoming")

    assert resp.status_code == 200
    data = resp.json()
    assert data["direction"] == "incoming"
    assert data["center"]["id"] == "repo::demo::class::Item"
    assert len(data["neighbors"]) == 1
    assert data["neighbors"][0]["id"] == "repo::demo::file::models.py"
    assert len(data["relationships"]) == 1
    assert data["relationships"][0]["target"] == "repo::demo::class::Item"
    assert data["relationships"][0]["source"] == "repo::demo::file::models.py"


def test_neighbors_outgoing_relationship_selection():
    """Verify direction=outgoing returns relationships whose source is the center entity."""
    center_props = {
        "id": "repo::demo::class::Item",
        "repo_id": "repo::demo",
        "name": "Item",
        "qualified_name": "models.Item",
        "file_path": "models.py",
        "language": "python",
        "start_line": 6,
        "end_line": 20,
        "start_byte": 50,
        "end_byte": 200,
    }
    base_props = {
        "id": "repo::demo::class::BaseEntity",
        "repo_id": "repo::demo",
        "name": "BaseEntity",
        "qualified_name": "base.BaseEntity",
        "file_path": "base.py",
        "language": "python",
        "start_line": 1,
        "end_line": 15,
        "start_byte": 0,
        "end_byte": 150,
    }
    # Outgoing INHERITS edge: Item -> BaseEntity
    edges = [
        {
            "source_id": "repo::demo::class::Item",
            "target_id": "repo::demo::class::BaseEntity",
            "rel_type": "INHERITS",
            "properties": {},
        }
    ]

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_neighbors_record(
        center_props, "Class", edges, [base_props], [["Class"]]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::class::Item/neighbors?direction=outgoing")

    assert resp.status_code == 200
    data = resp.json()
    assert data["direction"] == "outgoing"
    assert data["center"]["id"] == "repo::demo::class::Item"
    assert len(data["neighbors"]) == 1
    assert data["neighbors"][0]["id"] == "repo::demo::class::BaseEntity"
    assert len(data["relationships"]) == 1
    assert data["relationships"][0]["source"] == "repo::demo::class::Item"
    assert data["relationships"][0]["target"] == "repo::demo::class::BaseEntity"


def test_neighbors_both_direction_selection():
    """Verify direction=both (the default) returns incident relationships in both directions."""
    center_props = {
        "id": "repo::demo::class::Item",
        "repo_id": "repo::demo",
        "name": "Item",
        "qualified_name": "models.Item",
        "file_path": "models.py",
        "language": "python",
        "start_line": 6,
        "end_line": 20,
        "start_byte": 50,
        "end_byte": 200,
    }
    file_props = {
        "id": "repo::demo::file::models.py",
        "repo_id": "repo::demo",
        "path": "models.py",
        "language": "python",
        "start_line": 1,
        "end_line": 50,
        "start_byte": 0,
        "end_byte": 500,
    }
    base_props = {
        "id": "repo::demo::class::BaseEntity",
        "repo_id": "repo::demo",
        "name": "BaseEntity",
        "qualified_name": "base.BaseEntity",
        "file_path": "base.py",
        "language": "python",
        "start_line": 1,
        "end_line": 15,
        "start_byte": 0,
        "end_byte": 150,
    }
    edges = [
        {
            "source_id": "repo::demo::file::models.py",
            "target_id": "repo::demo::class::Item",
            "rel_type": "CONTAINS",
            "properties": {},
        },
        {
            "source_id": "repo::demo::class::Item",
            "target_id": "repo::demo::class::BaseEntity",
            "rel_type": "INHERITS",
            "properties": {},
        },
    ]

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_neighbors_record(
        center_props, "Class", edges, [file_props, base_props], [["File"], ["Class"]]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    # When direction is omitted, default is "both"
    resp = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::class::Item/neighbors")

    assert resp.status_code == 200
    data = resp.json()
    assert data["direction"] == "both"
    assert len(data["neighbors"]) == 2
    assert len(data["relationships"]) == 2
    assert data["total_relationships"] == 2
    assert data["total_neighbors"] == 2


def test_neighbors_invalid_direction_values():
    """Verify endpoint rejects invalid direction parameters with HTTP 422."""
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::class::Item/neighbors?direction=invalid_dir")
    assert resp.status_code == 422

    # Direct service validation check
    service = RepositoryService()
    with pytest.raises(Exception) as exc_info:
        service.get_entity_neighbors("repo::demo", "class::Item", direction="invalid_dir")
    assert "Invalid direction" in str(exc_info.value)


def test_neighbors_entity_with_no_relationships():
    """Verify an isolated entity with 0 relationships returns 200 with center present and empty collections."""
    center_props = {
        "id": "repo::demo::class::Isolated",
        "repo_id": "repo::demo",
        "name": "Isolated",
        "qualified_name": "mod.Isolated",
        "file_path": "mod.py",
        "language": "python",
        "start_line": 5,
        "end_line": 10,
        "start_byte": 50,
        "end_byte": 100,
    }

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_neighbors_record(
        center_props, "Class", [], [], []
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::class::Isolated/neighbors")

    assert resp.status_code == 200
    data = resp.json()
    assert data["center"]["id"] == "repo::demo::class::Isolated"
    assert data["neighbors"] == []
    assert data["relationships"] == []
    assert data["total_relationships"] == 0
    assert data["returned_relationships"] == 0
    assert data["total_neighbors"] == 0
    assert data["returned_neighbors"] == 0
    assert data["has_more"] is False
    assert data["truncated"] is False


def test_neighbors_self_loop_under_direction_both():
    """Verify self-loop relationships are not duplicated under direction=both and center is not added to neighbors."""
    center_props = {
        "id": "repo::demo::function::recurse",
        "repo_id": "repo::demo",
        "name": "recurse",
        "qualified_name": "math.recurse",
        "file_path": "math.py",
        "language": "python",
        "start_line": 10,
        "end_line": 20,
        "start_byte": 100,
        "end_byte": 200,
    }
    # Self-loop: recurse -> CALLS -> recurse
    self_loop_edge = [
        {
            "source_id": "repo::demo::function::recurse",
            "target_id": "repo::demo::function::recurse",
            "rel_type": "CALLS",
            "properties": {"start_line": 15},
        }
    ]

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_neighbors_record(
        center_props, "Function", self_loop_edge, [center_props], [["Function"]]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::function::recurse/neighbors?direction=both")

    assert resp.status_code == 200
    data = resp.json()
    # Edge returned once
    assert len(data["relationships"]) == 1
    assert data["relationships"][0]["source"] == "repo::demo::function::recurse"
    assert data["relationships"][0]["target"] == "repo::demo::function::recurse"
    # Center is not duplicated in neighbors list
    assert data["neighbors"] == []
    assert data["total_relationships"] == 1
    assert data["total_neighbors"] == 0


def test_neighbors_multiple_relationship_types_between_same_two_nodes():
    """Verify multiple edges between the same two nodes return each edge once and the neighbor node once."""
    center_props = {
        "id": "repo::demo::function::a",
        "repo_id": "repo::demo",
        "name": "a",
        "qualified_name": "mod.a",
        "file_path": "mod.py",
        "language": "python",
        "start_line": 1,
        "end_line": 10,
        "start_byte": 0,
        "end_byte": 100,
    }
    nbr_props = {
        "id": "repo::demo::function::b",
        "repo_id": "repo::demo",
        "name": "b",
        "qualified_name": "mod.b",
        "file_path": "mod.py",
        "language": "python",
        "start_line": 15,
        "end_line": 25,
        "start_byte": 150,
        "end_byte": 250,
    }
    # Two distinct calls from a to b at lines 3 and 7
    edges = [
        {
            "source_id": "repo::demo::function::a",
            "target_id": "repo::demo::function::b",
            "rel_type": "CALLS",
            "properties": {"start_line": 3},
        },
        {
            "source_id": "repo::demo::function::a",
            "target_id": "repo::demo::function::b",
            "rel_type": "CALLS",
            "properties": {"start_line": 7},
        },
    ]

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_neighbors_record(
        center_props, "Function", edges, [nbr_props], [["Function"]]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::function::a/neighbors")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["neighbors"]) == 1
    assert data["neighbors"][0]["id"] == "repo::demo::function::b"
    assert len(data["relationships"]) == 2
    # Distinct deterministic edge IDs generated via line numbers
    edge_ids = [r["id"] for r in data["relationships"]]
    assert len(set(edge_ids)) == 2


def test_neighbors_pagination_over_multiple_pages():
    """Verify relationship-based pagination across multiple pages."""
    center_props = {
        "id": "repo::demo::class::Hub",
        "repo_id": "repo::demo",
        "name": "Hub",
        "qualified_name": "mod.Hub",
        "file_path": "mod.py",
        "language": "python",
        "start_line": 1,
        "end_line": 50,
        "start_byte": 0,
        "end_byte": 500,
    }
    nbrs = [
        {
            "id": f"repo::demo::class::Node_{i}",
            "repo_id": "repo::demo",
            "name": f"Node_{i}",
            "qualified_name": f"mod.Node_{i}",
            "file_path": "mod.py",
            "language": "python",
            "start_line": i * 10 + 1,
            "end_line": i * 10 + 5,
            "start_byte": i * 50,
            "end_byte": i * 50 + 40,
        }
        for i in range(5)
    ]
    edges = [
        {
            "source_id": "repo::demo::class::Hub",
            "target_id": f"repo::demo::class::Node_{i}",
            "rel_type": "CALLS",
            "properties": {"start_line": i * 10 + 2},
        }
        for i in range(5)
    ]
    nbr_labels = [["Class"] for _ in range(5)]

    mock_session = MagicMock(spec=Session)

    def mock_run_paging(query, **params):
        offset = params.get("offset", 0)
        limit = params.get("limit", 50)
        res = MagicMock()
        res.single.return_value = _build_mock_neighbors_record(
            center_props, "Class", edges, nbrs, nbr_labels, offset=offset, limit=limit
        )
        return res

    mock_session.run.side_effect = mock_run_paging
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)

    # Page 1: limit=2, offset=0
    resp1 = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::class::Hub/neighbors?limit=2&offset=0")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1["relationships"]) == 2
    assert data1["total_relationships"] == 5
    assert data1["returned_relationships"] == 2
    assert data1["has_more"] is True
    assert data1["truncated"] is True

    # Page 2: limit=2, offset=2
    resp2 = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::class::Hub/neighbors?limit=2&offset=2")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["relationships"]) == 2
    assert data2["has_more"] is True

    # Page 3: limit=2, offset=4 (last)
    resp3 = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::class::Hub/neighbors?limit=2&offset=4")
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert len(data3["relationships"]) == 1
    assert data3["has_more"] is False
    assert data3["truncated"] is True


def test_neighbors_deterministic_ordering():
    """Verify repeated calls return identical deterministic ordering of neighbors and relationships."""
    center_props = {
        "id": "repo::demo::class::Hub",
        "repo_id": "repo::demo",
        "name": "Hub",
        "qualified_name": "mod.Hub",
        "file_path": "mod.py",
        "language": "python",
        "start_line": 1,
        "end_line": 50,
        "start_byte": 0,
        "end_byte": 500,
    }
    nbrs = [
        {
            "id": f"repo::demo::class::Node_{i}",
            "repo_id": "repo::demo",
            "name": f"Node_{i}",
            "qualified_name": f"mod.Node_{i}",
            "file_path": "mod.py",
            "language": "python",
            "start_line": i * 10 + 1,
            "end_line": i * 10 + 5,
            "start_byte": i * 50,
            "end_byte": i * 50 + 40,
        }
        for i in [3, 1, 4, 0, 2]
    ]
    edges = [
        {
            "source_id": "repo::demo::class::Hub",
            "target_id": f"repo::demo::class::Node_{i}",
            "rel_type": "CALLS",
            "properties": {"start_line": i * 10 + 2},
        }
        for i in [3, 1, 4, 0, 2]
    ]

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_neighbors_record(
        center_props, "Class", edges, nbrs, [["Class"] for _ in range(5)]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resps = [
        client.get("/api/v1/repositories/repo::demo/entities/repo::demo::class::Hub/neighbors")
        for _ in range(3)
    ]
    assert all(r.status_code == 200 for r in resps)
    payloads = [r.json() for r in resps]

    for p in payloads[1:]:
        assert [n["id"] for n in p["neighbors"]] == [n["id"] for n in payloads[0]["neighbors"]]
        assert [r["id"] for r in p["relationships"]] == [r["id"] for r in payloads[0]["relationships"]]


def test_neighbors_limit_and_offset_validation():
    """Verify limit and offset boundary validation."""
    client = TestClient(app, raise_server_exceptions=False)

    # limit > 200 -> 422
    assert client.get("/api/v1/repositories/repo::demo/entities/class::A/neighbors?limit=201").status_code == 422

    # limit < 1 -> 422
    assert client.get("/api/v1/repositories/repo::demo/entities/class::A/neighbors?limit=0").status_code == 422

    # offset < 0 -> 422
    assert client.get("/api/v1/repositories/repo::demo/entities/class::A/neighbors?offset=-1").status_code == 422

    # Direct service boundary checks
    service = RepositoryService()
    with pytest.raises(Exception) as exc1:
        service.get_entity_neighbors("repo::demo", "class::A", limit=201)
    assert "cannot exceed 200" in str(exc1.value)

    with pytest.raises(Exception) as exc2:
        service.get_entity_neighbors("repo::demo", "class::A", limit=0)
    assert "Limit must be >= 1" in str(exc2.value)


def test_neighbors_missing_repository_returns_404():
    """Verify neighbors of a nonexistent repository returns HTTP 404."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = Record(
        [
            ("repo_exists", False),
            ("center_props", None),
            ("center_labels", []),
            ("total_relationships", 0),
            ("total_neighbors", 0),
            ("edges", []),
            ("neighbor_props", []),
            ("neighbor_labels", []),
        ]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::missing/entities/class::A/neighbors")
    assert resp.status_code == 404
    assert "Repository 'repo::missing' not found" in resp.json()["detail"]


def test_neighbors_missing_entity_returns_404():
    """Verify neighbors of a nonexistent entity in repository returns HTTP 404."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = Record(
        [
            ("repo_exists", True),
            ("center_props", None),
            ("center_labels", []),
            ("total_relationships", 0),
            ("total_neighbors", 0),
            ("edges", []),
            ("neighbor_props", []),
            ("neighbor_labels", []),
        ]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/class::missing/neighbors")
    assert resp.status_code == 404
    assert "Entity 'class::missing' not found in repository 'repo::demo'" in resp.json()["detail"]


def test_neighbors_entity_belonging_to_different_repository_returns_404():
    """Verify neighbors of an entity belonging to another repository returns HTTP 404."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = Record(
        [
            ("repo_exists", True),
            ("center_props", None),
            ("center_labels", []),
            ("total_relationships", 0),
            ("total_neighbors", 0),
            ("edges", []),
            ("neighbor_props", []),
            ("neighbor_labels", []),
        ]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::repo_a/entities/repo::repo_b::file::secret.py/neighbors")
    assert resp.status_code == 404
    assert "Entity 'repo::repo_b::file::secret.py' not found in repository 'repo::repo_a'" in resp.json()["detail"]


def test_neighbors_repository_isolation_of_neighboring_entities():
    """Verify Cypher query parameter strictly scopes queries to the requested repo_id."""
    mock_session = MagicMock(spec=Session)
    center = {
        "id": "repo::iso::class::A",
        "repo_id": "repo::iso",
        "name": "A",
        "qualified_name": "a.A",
        "file_path": "a.py",
        "language": "python",
        "start_line": 1,
        "end_line": 10,
        "start_byte": 0,
        "end_byte": 100,
    }
    mock_session.run.return_value.single.return_value = _build_mock_neighbors_record(
        center, "Class", [], [], []
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::iso/entities/repo::iso::class::A/neighbors")
    assert resp.status_code == 200

    call_params = mock_session.run.call_args[1]
    assert call_params["repo_id"] == "repo::iso"


def test_neighbors_endpoint_presence_invariant():
    """Verify dangling edges pointing to unreturned nodes are strictly excluded."""
    center = {
        "id": "repo::demo::class::A",
        "repo_id": "repo::demo",
        "name": "A",
        "qualified_name": "a.A",
        "file_path": "a.py",
        "language": "python",
        "start_line": 1,
        "end_line": 10,
        "start_byte": 0,
        "end_byte": 100,
    }
    nbr = {
        "id": "repo::demo::class::B",
        "repo_id": "repo::demo",
        "name": "B",
        "qualified_name": "b.B",
        "file_path": "b.py",
        "language": "python",
        "start_line": 1,
        "end_line": 10,
        "start_byte": 0,
        "end_byte": 100,
    }
    # One valid edge to B, one dangling edge to unknown node C
    edges = [
        {"source_id": "repo::demo::class::A", "target_id": "repo::demo::class::B", "rel_type": "CALLS", "properties": {}},
        {"source_id": "repo::demo::class::A", "target_id": "repo::demo::class::C_unreturned", "rel_type": "CALLS", "properties": {}},
    ]

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = Record(
        [
            ("repo_exists", True),
            ("center_props", center),
            ("center_labels", ["Class"]),
            ("total_relationships", 2),
            ("total_neighbors", 1),
            ("edges", edges),
            ("neighbor_props", [nbr]),
            ("neighbor_labels", [["Class"]]),
        ]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::class::A/neighbors")
    assert resp.status_code == 200
    data = resp.json()

    valid_ids = {data["center"]["id"]} | {n["id"] for n in data["neighbors"]}
    assert len(data["relationships"]) == 1
    for r in data["relationships"]:
        assert r["source"] in valid_ids
        assert r["target"] in valid_ids


def test_neighbors_does_not_invoke_full_graph_reconstruction():
    """Verify neighbor inspection does not invoke GraphRetriever.get_repository_graph."""
    center = {
        "id": "repo::demo::file::a.py",
        "repo_id": "repo::demo",
        "path": "a.py",
        "language": "python",
        "start_line": 1,
        "end_line": 10,
        "start_byte": 0,
        "end_byte": 100,
    }
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_neighbors_record(
        center, "File", [], [], []
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    with patch.object(GraphRetriever, "get_repository_graph") as mock_full:
        resp = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::file::a.py/neighbors")
        assert resp.status_code == 200
        mock_full.assert_not_called()


def test_neighbors_database_unavailable_returns_503():
    """Verify neighbor inspection returns 503 when Neo4j is unreachable."""
    set_driver(None)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/repo::demo::file::a.py/neighbors")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Database service unavailable"




def _build_mock_search_record(
    repo_exists: bool,
    total_matches: int,
    entities_props: list[dict[str, Any]],
    entities_labels: list[list[str]],
) -> Record:
    """Helper to construct a mock Neo4j Record for search_entities."""
    return Record(
        [
            ("repo_exists", repo_exists),
            ("total_matches", total_matches),
            ("entities_props", entities_props),
            ("entities_labels", entities_labels),
        ]
    )


def test_search_case_insensitive_matching():
    """Verify entity search performs case-insensitive matching."""
    func_props = {
        "id": "repo::demo::func::process_data",
        "repo_id": "repo::demo",
        "name": "process_data",
        "qualified_name": "app.process_data",
        "file_path": "app.py",
        "language": "python",
        "start_line": 15,
        "end_line": 35,
        "start_byte": 150,
        "end_byte": 350,
    }

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_search_record(
        True, 1, [func_props], [["Function"]]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)

    for q_val in ["process_data", "PROCESS_DATA", "PrOcEsS_DaTa"]:
        resp = client.get(f"/api/v1/repositories/repo::demo/entities/search?q={q_val}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_matches"] == 1
        assert len(data["entities"]) == 1
        assert data["entities"][0]["name"] == "process_data"
        assert data["entities"][0]["type"] == "Function"
        # Verify both 'entities' and 'results' fields are present and identical
        assert data["results"] == data["entities"]

    # Verify retriever received lowercased query parameter
    assert mock_session.run.call_args[1]["q_lower"] == "process_data"


def test_search_substring_matching_on_entity_names():
    """Verify substring matching retrieves entities where query is a substring."""
    props1 = {
        "id": "repo::demo::class::OrderProcessor",
        "repo_id": "repo::demo",
        "name": "OrderProcessor",
        "qualified_name": "orders.OrderProcessor",
        "file_path": "orders.py",
        "language": "python",
        "start_line": 10,
        "end_line": 50,
        "start_byte": 100,
        "end_byte": 500,
    }
    props2 = {
        "id": "repo::demo::func::process_item",
        "repo_id": "repo::demo",
        "name": "process_item",
        "qualified_name": "orders.process_item",
        "file_path": "orders.py",
        "language": "python",
        "start_line": 55,
        "end_line": 70,
        "start_byte": 550,
        "end_byte": 700,
    }

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_search_record(
        True, 2, [props1, props2], [["Class"], ["Function"]]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/search?q=process")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_matches"] == 2
    assert len(data["entities"]) == 2
    assert data["entities"][0]["name"] == "OrderProcessor"
    assert data["entities"][1]["name"] == "process_item"


def test_search_matching_ids():
    """Verify entity search matches stable entity IDs."""
    props = {
        "id": "repo::demo::func::main.py:process_data",
        "repo_id": "repo::demo",
        "name": "process_data",
        "qualified_name": "main.process_data",
        "file_path": "main.py",
        "language": "python",
        "start_line": 1,
        "end_line": 10,
        "start_byte": 0,
        "end_byte": 100,
    }

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_search_record(
        True, 1, [props], [["Function"]]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/search?q=func::main.py")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_matches"] == 1
    assert data["entities"][0]["id"] == "repo::demo::func::main.py:process_data"


def test_search_matching_file_paths_and_qualified_names():
    """Verify search matches against file_path and qualified_name properties."""
    file_props = {
        "id": "repo::demo::file::services/data_service.py",
        "repo_id": "repo::demo",
        "path": "services/data_service.py",
        "language": "python",
        "start_line": 1,
        "end_line": 100,
        "start_byte": 0,
        "end_byte": 1500,
    }
    class_props = {
        "id": "repo::demo::class::DataService",
        "repo_id": "repo::demo",
        "name": "DataService",
        "qualified_name": "services.data_service.DataService",
        "file_path": "services/data_service.py",
        "language": "python",
        "start_line": 10,
        "end_line": 90,
        "start_byte": 100,
        "end_byte": 1400,
    }

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_search_record(
        True, 2, [file_props, class_props], [["File"], ["Class"]]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/search?q=services/data_service")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["entities"]) == 2
    assert data["entities"][0]["name"] == "services/data_service.py"
    assert data["entities"][1]["name"] == "DataService"


def test_search_empty_and_whitespace_only_validation():
    """Verify search rejects empty or pure whitespace query with HTTP 400 or 422."""
    client = TestClient(app, raise_server_exceptions=False)

    # Missing query parameter -> 422
    resp_missing = client.get("/api/v1/repositories/repo::demo/entities/search")
    assert resp_missing.status_code == 422

    # Empty query parameter -> 400 or 422
    resp_empty = client.get("/api/v1/repositories/repo::demo/entities/search?q=")
    assert resp_empty.status_code in (400, 422)

    # Whitespace-only query -> 400 Bad Request
    resp_ws = client.get("/api/v1/repositories/repo::demo/entities/search?q=%20%20%20")
    assert resp_ws.status_code == 400
    assert "cannot be empty" in resp_ws.json()["detail"]

    # Direct service validation check
    service = RepositoryService()
    with pytest.raises(Exception) as exc1:
        service.search_entities("repo::demo", q="")
    assert "cannot be empty" in str(exc1.value)

    with pytest.raises(Exception) as exc2:
        service.search_entities("repo::demo", q="   ")
    assert "cannot be empty" in str(exc2.value)

    # Exceeding 100 characters -> 422
    long_q = "a" * 101
    resp_long = client.get(f"/api/v1/repositories/repo::demo/entities/search?q={long_q}")
    assert resp_long.status_code == 422


def test_search_limit_and_offset_validation():
    """Verify limit and offset boundary validation for search."""
    client = TestClient(app, raise_server_exceptions=False)

    # limit > 200 -> 422
    assert client.get("/api/v1/repositories/repo::demo/entities/search?q=test&limit=201").status_code == 422

    # limit < 1 -> 422
    assert client.get("/api/v1/repositories/repo::demo/entities/search?q=test&limit=0").status_code == 422

    # offset < 0 -> 422
    assert client.get("/api/v1/repositories/repo::demo/entities/search?q=test&offset=-1").status_code == 422

    # Direct service boundary checks
    service = RepositoryService()
    with pytest.raises(Exception) as exc1:
        service.search_entities("repo::demo", q="test", limit=201)
    assert "cannot exceed 200" in str(exc1.value)

    with pytest.raises(Exception) as exc2:
        service.search_entities("repo::demo", q="test", limit=0)
    assert "Limit must be >= 1" in str(exc2.value)

    with pytest.raises(Exception) as exc3:
        service.search_entities("repo::demo", q="test", offset=-1)
    assert "Offset must be >= 0" in str(exc3.value)


def test_search_pagination_across_multiple_pages():
    """Verify pagination across multiple pages with correct metadata."""
    total_matches = 5
    items = [
        {
            "id": f"repo::demo::func::fn_{i}",
            "repo_id": "repo::demo",
            "name": f"fn_{i}",
            "qualified_name": f"app.fn_{i}",
            "file_path": "app.py",
            "language": "python",
            "start_line": i * 10 + 1,
            "end_line": i * 10 + 9,
            "start_byte": i * 50,
            "end_byte": i * 50 + 40,
        }
        for i in range(5)
    ]

    mock_session = MagicMock(spec=Session)
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)
    client = TestClient(app, raise_server_exceptions=False)

    # Page 1: offset=0, limit=2
    mock_session.run.return_value.single.return_value = _build_mock_search_record(
        True, total_matches, items[0:2], [["Function"], ["Function"]]
    )
    resp1 = client.get("/api/v1/repositories/repo::demo/entities/search?q=fn&limit=2&offset=0")
    assert resp1.status_code == 200
    p1 = resp1.json()
    assert p1["total_matches"] == 5
    assert p1["returned_matches"] == 2
    assert p1["has_more"] is True
    assert p1["truncated"] is True
    assert [e["name"] for e in p1["entities"]] == ["fn_0", "fn_1"]

    # Page 2: offset=2, limit=2
    mock_session.run.return_value.single.return_value = _build_mock_search_record(
        True, total_matches, items[2:4], [["Function"], ["Function"]]
    )
    resp2 = client.get("/api/v1/repositories/repo::demo/entities/search?q=fn&limit=2&offset=2")
    assert resp2.status_code == 200
    p2 = resp2.json()
    assert p2["total_matches"] == 5
    assert p2["returned_matches"] == 2
    assert p2["has_more"] is True
    assert p2["truncated"] is True
    assert [e["name"] for e in p2["entities"]] == ["fn_2", "fn_3"]

    # Page 3: offset=4, limit=2
    mock_session.run.return_value.single.return_value = _build_mock_search_record(
        True, total_matches, items[4:5], [["Function"]]
    )
    resp3 = client.get("/api/v1/repositories/repo::demo/entities/search?q=fn&limit=2&offset=4")
    assert resp3.status_code == 200
    p3 = resp3.json()
    assert p3["total_matches"] == 5
    assert p3["returned_matches"] == 1
    assert p3["has_more"] is False
    assert p3["truncated"] is True
    assert [e["name"] for e in p3["entities"]] == ["fn_4"]


def test_search_deterministic_ordering():
    """Verify repeated search calls preserve deterministic ordering."""
    items = [
        {
            "id": f"repo::demo::func::func_{i}",
            "repo_id": "repo::demo",
            "name": f"func_{i}",
            "qualified_name": f"mod.func_{i}",
            "file_path": "mod.py",
            "language": "python",
            "start_line": i * 10 + 1,
            "end_line": i * 10 + 8,
            "start_byte": i * 40,
            "end_byte": i * 40 + 30,
        }
        for i in [3, 1, 4, 0, 2]
    ]

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_search_record(
        True, 5, items, [["Function"] for _ in range(5)]
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resps = [
        client.get("/api/v1/repositories/repo::demo/entities/search?q=func")
        for _ in range(3)
    ]
    assert all(r.status_code == 200 for r in resps)
    payloads = [r.json() for r in resps]

    first_ids = [e["id"] for e in payloads[0]["entities"]]
    for p in payloads[1:]:
        assert [e["id"] for e in p["entities"]] == first_ids


def test_search_no_matches_returns_200_with_empty_list():
    """Verify search with 0 matches returns HTTP 200 with empty list."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_search_record(
        True, 0, [], []
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/search?q=nonexistent_xyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_matches"] == 0
    assert data["returned_matches"] == 0
    assert data["entities"] == []
    assert data["results"] == []
    assert data["has_more"] is False
    assert data["truncated"] is False


def test_search_missing_repository_returns_404():
    """Verify searching a nonexistent repository returns HTTP 404."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_search_record(
        False, 0, [], []
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::missing/entities/search?q=test")
    assert resp.status_code == 404
    assert "Repository 'repo::missing' not found" in resp.json()["detail"]


def test_search_repository_isolation():
    """Verify search executes against repository-isolated parameters."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_search_record(
        True, 0, [], []
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::isolated_repo/entities/search?q=test")
    assert resp.status_code == 200

    # Ensure repository ID is bound in Cypher kwargs
    assert mock_session.run.call_args[1]["repo_id"] == "repo::isolated_repo"


def test_search_different_entity_types_and_type_filter():
    """Verify search correctly handles all 7 entity types and type filtering."""
    props_all = [
        {
            "id": "repo::demo::file::app.py",
            "repo_id": "repo::demo",
            "path": "app.py",
            "language": "python",
            "start_line": 1,
            "end_line": 50,
            "start_byte": 0,
            "end_byte": 500,
        },
        {
            "id": "repo::demo::class::Worker",
            "repo_id": "repo::demo",
            "name": "Worker",
            "qualified_name": "app.Worker",
            "file_path": "app.py",
            "language": "python",
            "start_line": 5,
            "end_line": 20,
            "start_byte": 50,
            "end_byte": 200,
        },
        {
            "id": "repo::demo::func::run_task",
            "repo_id": "repo::demo",
            "name": "run_task",
            "qualified_name": "app.run_task",
            "file_path": "app.py",
            "language": "python",
            "start_line": 22,
            "end_line": 30,
            "start_byte": 220,
            "end_byte": 300,
        },
        {
            "id": "repo::demo::method::Worker.execute",
            "repo_id": "repo::demo",
            "name": "execute",
            "qualified_name": "app.Worker.execute",
            "file_path": "app.py",
            "language": "python",
            "start_line": 10,
            "end_line": 18,
            "start_byte": 100,
            "end_byte": 180,
        },
        {
            "id": "repo::demo::mod::app",
            "repo_id": "repo::demo",
            "name": "app",
            "qualified_name": "app",
            "file_path": "app.py",
        },
        {
            "id": "repo::demo::imp::os",
            "repo_id": "repo::demo",
            "file_path": "app.py",
            "module_name": "os",
            "imported_name": "path",
            "alias": None,
            "start_line": 1,
            "end_line": 1,
            "start_byte": 0,
            "end_byte": 15,
        },
        {
            "id": "repo::demo",
            "name": "demo_repo",
            "source": "/repo",
            "created_at": "2026-01-01T00:00:00",
        },
    ]
    labels_all = [
        ["File"],
        ["Class"],
        ["Function"],
        ["Method"],
        ["Module"],
        ["Import"],
        ["Repository"],
    ]

    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_search_record(
        True, 7, props_all, labels_all
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/search?q=app")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["entities"]) == 7
    types = [e["type"] for e in data["entities"]]
    assert types == ["File", "Class", "Function", "Method", "Module", "Import", "Repository"]

    # Valid type filter
    resp_type = client.get("/api/v1/repositories/repo::demo/entities/search?q=app&type=Class")
    assert resp_type.status_code == 200
    assert mock_session.run.call_args[1]["type_filter"] == "Class"

    # Case-insensitive type filter
    resp_type_lower = client.get("/api/v1/repositories/repo::demo/entities/search?q=app&type=function")
    assert resp_type_lower.status_code == 200
    assert mock_session.run.call_args[1]["type_filter"] == "Function"

    # Invalid type filter -> 400 Bad Request
    resp_bad_type = client.get("/api/v1/repositories/repo::demo/entities/search?q=app&type=InvalidType")
    assert resp_bad_type.status_code == 400
    assert "Unsupported entity type filter: 'InvalidType'" in resp_bad_type.json()["detail"]


def test_search_wildcard_and_punctuation_treated_literally():
    """Verify wildcard and punctuation characters (*, ?, %, _) are treated strictly literally."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_search_record(
        True, 0, [], []
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    special_query = "calc_*_func?%_#"
    resp = client.get("/api/v1/repositories/repo::demo/entities/search", params={"q": special_query})
    assert resp.status_code == 200

    # Verify query string was bound literally without regexp interpretation
    assert mock_session.run.call_args[1]["q_lower"] == special_query.lower()


def test_search_pagination_metadata():
    """Verify all pagination metadata fields are correctly returned."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_search_record(
        True, 50, [], []
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/search?q=core&limit=10&offset=20&type=Module")
    assert resp.status_code == 200
    data = resp.json()

    assert data["repository_id"] == "repo::demo"
    assert data["query"] == "core"
    assert data["type_filter"] == "Module"
    assert data["total_matches"] == 50
    assert data["returned_matches"] == 0
    assert data["has_more"] is True
    assert data["truncated"] is True
    assert data["offset"] == 20
    assert data["limit"] == 10


def test_search_does_not_invoke_full_graph_reconstruction():
    """Verify search bypasses full-graph reconstruction."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = _build_mock_search_record(
        True, 0, [], []
    )
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)
    with patch.object(GraphRetriever, "get_repository_graph") as mock_full:
        resp = client.get("/api/v1/repositories/repo::demo/entities/search?q=test")
        assert resp.status_code == 200
        mock_full.assert_not_called()


def test_search_database_unavailable_returns_503():
    """Verify search returns 503 when Neo4j is unreachable."""
    set_driver(None)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/api/v1/repositories/repo::demo/entities/search?q=test")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Database service unavailable"


def test_search_route_matching_alongside_children_and_neighbors():
    """Verify route precedence: /entities/search does not collide with {entity_id:path}/children or neighbors."""
    mock_session = MagicMock(spec=Session)
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session
    set_driver(mock_driver)

    client = TestClient(app, raise_server_exceptions=False)

    # 1. Search endpoint
    mock_session.run.return_value.single.return_value = _build_mock_search_record(
        True, 0, [], []
    )
    resp_search = client.get("/api/v1/repositories/repo::demo/entities/search?q=foo")
    assert resp_search.status_code == 200
    assert "total_matches" in resp_search.json()

    # 2. Children endpoint for an entity whose ID happens to be 'search'
    mock_session.run.return_value.single.return_value = _build_mock_children_record(
        {"id": "search", "name": "search", "source": "/"}, "Repository", [], []
    )
    resp_child = client.get("/api/v1/repositories/repo::demo/entities/search/children")
    assert resp_child.status_code == 200
    assert "total_children" in resp_child.json()

    # 3. Neighbors endpoint for an entity whose ID happens to be 'search'
    mock_session.run.return_value.single.return_value = _build_mock_neighbors_record(
        {"id": "search", "name": "search", "source": "/"}, "Repository", [], [], []
    )
    resp_nbr = client.get("/api/v1/repositories/repo::demo/entities/search/neighbors")
    assert resp_nbr.status_code == 200
    assert "total_neighbors" in resp_nbr.json()

    # 4. Complex path with slashes for children
    mock_session.run.return_value.single.return_value = _build_mock_children_record(
        {"id": "nested/path/to/mod.py", "repo_id": "repo::demo", "path": "nested/path/to/mod.py", "language": "python", "start_line": 1, "end_line": 10, "start_byte": 0, "end_byte": 100},
        "File",
        [],
        [],
    )
    resp_nested_child = client.get("/api/v1/repositories/repo::demo/entities/nested/path/to/mod.py/children")
    assert resp_nested_child.status_code == 200
    assert "total_children" in resp_nested_child.json()

    # 5. Complex path with slashes for neighbors
    mock_session.run.return_value.single.return_value = _build_mock_neighbors_record(
        {"id": "nested/path/to/mod.py", "repo_id": "repo::demo", "path": "nested/path/to/mod.py", "language": "python", "start_line": 1, "end_line": 10, "start_byte": 0, "end_byte": 100},
        "File",
        [],
        [],
        [],
    )
    resp_nested_nbr = client.get("/api/v1/repositories/repo::demo/entities/nested/path/to/mod.py/neighbors")
    assert resp_nested_nbr.status_code == 200
    assert "total_neighbors" in resp_nested_nbr.json()
