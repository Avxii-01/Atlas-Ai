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


