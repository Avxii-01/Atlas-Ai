"""Automated tests for Neo4j graph retrieval and UCM model reconstruction."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest
from neo4j import Driver, Record, Session

from app.db.graph_retriever import (
    GraphRetriever,
    Neo4jRetrievalError,
    get_entity_by_id,
    get_relationships,
    get_repository_graph,
    record_to_entity,
    record_to_relationship,
)
from app.db.neo4j import Neo4jConnectionError, set_driver
from app.db.schema import NodeLabel
from app.resolver.relationship_resolver import resolve_repository
from app.ucm.entities import (
    Class,
    File,
    Function,
    Import,
    Method,
    Module,
    Repository,
)
from app.ucm.model import UnifiedCodeModel
from app.ucm.relationships import RelationshipType

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "atlas_fixture"


@pytest.fixture(autouse=True)
def reset_driver_state():
    """Ensure driver state is reset before and after every test."""
    set_driver(None)
    yield
    set_driver(None)


def test_record_to_entity_all_seven_types():
    """Verify record_to_entity accurately reconstructs all 7 UCM entity types."""
    repo_props = {"id": "repo::demo", "name": "demo", "source": "/src", "created_at": "2026-10-09T00:00:00Z"}
    repo = record_to_entity(NodeLabel.REPOSITORY.value, repo_props)
    assert isinstance(repo, Repository)
    assert repo.id == "repo::demo"
    assert repo.created_at == "2026-10-09T00:00:00Z"

    file_props = {
        "id": "repo::demo::file::app.py",
        "repo_id": "repo::demo",
        "path": "app.py",
        "language": "python",
        "start_line": 1,
        "end_line": 20,
        "start_byte": 0,
        "end_byte": 100,
    }
    file_ent = record_to_entity(NodeLabel.FILE.value, file_props)
    assert isinstance(file_ent, File)
    assert file_ent.path == "app.py"

    mod_props = {
        "id": "repo::demo::module::app",
        "repo_id": "repo::demo",
        "name": "app",
        "qualified_name": "app",
        "file_path": "app.py",
    }
    mod_ent = record_to_entity(NodeLabel.MODULE.value, mod_props)
    assert isinstance(mod_ent, Module)
    assert mod_ent.qualified_name == "app"

    cls_props = {
        "id": "repo::demo::class::app.App",
        "repo_id": "repo::demo",
        "name": "App",
        "qualified_name": "app.App",
        "file_path": "app.py",
        "language": "python",
        "start_line": 5,
        "end_line": 15,
        "start_byte": 40,
        "end_byte": 150,
        "docstring": "Main app.",
    }
    cls_ent = record_to_entity(NodeLabel.CLASS.value, cls_props)
    assert isinstance(cls_ent, Class)
    assert cls_ent.docstring == "Main app."

    func_props = {
        "id": "repo::demo::function::app.run",
        "repo_id": "repo::demo",
        "name": "run",
        "qualified_name": "app.run",
        "file_path": "app.py",
        "language": "python",
        "start_line": 16,
        "end_line": 18,
        "start_byte": 160,
        "end_byte": 180,
    }
    func_ent = record_to_entity(NodeLabel.FUNCTION.value, func_props)
    assert isinstance(func_ent, Function)
    assert func_ent.docstring is None

    meth_props = {
        "id": "repo::demo::method::app.App.start",
        "repo_id": "repo::demo",
        "name": "start",
        "qualified_name": "app.App.start",
        "file_path": "app.py",
        "language": "python",
        "start_line": 8,
        "end_line": 10,
        "start_byte": 70,
        "end_byte": 95,
        "docstring": None,
    }
    meth_ent = record_to_entity(NodeLabel.METHOD.value, meth_props)
    assert isinstance(meth_ent, Method)
    assert meth_ent.name == "start"

    import_props = {
        "id": "repo::demo::import::app.py::L2::os",
        "repo_id": "repo::demo",
        "file_path": "app.py",
        "module_name": "os",
        "imported_name": "path",
        "alias": "osp",
        "start_line": 2,
        "end_line": 2,
    }
    import_ent = record_to_entity(NodeLabel.IMPORT.value, import_props)
    assert isinstance(import_ent, Import)
    assert import_ent.alias == "osp"


def test_record_to_relationship_reconstruction():
    """Verify record_to_relationship reconstructs typed Relationship and source evidence."""
    props = {
        "start_line": 12,
        "start_column": 4,
        "end_line": 12,
        "end_column": 20,
        "start_byte": 150,
        "end_byte": 166,
        "alias": "srv",
    }
    rel = record_to_relationship(
        source_id="repo::a::file::app.py",
        target_id="repo::a::module::services",
        rel_type="IMPORTS",
        properties=props,
    )

    assert rel.rel_type == RelationshipType.IMPORTS
    assert rel.source_id == "repo::a::file::app.py"
    assert rel.target_id == "repo::a::module::services"
    assert rel.location is not None
    assert rel.location.start_point.line == 12
    assert rel.location.start_point.column == 4
    assert rel.location.end_point.line == 12
    assert rel.location.end_point.column == 20
    assert rel.location.start_byte == 150
    assert rel.location.end_byte == 166
    assert rel.metadata == {"alias": "srv"}


def test_get_repository_found_and_not_found():
    """Verify get_repository returns Repository when present and None when absent."""
    mock_session = MagicMock(spec=Session)

    # 1. Found scenario
    mock_session.run.return_value.single.return_value = {
        "props": {"id": "repo::my_repo", "name": "my_repo", "source": "/src"}
    }
    retriever = GraphRetriever()
    repo = retriever.get_repository("repo::my_repo", session=mock_session)
    assert isinstance(repo, Repository)
    assert repo.id == "repo::my_repo"

    # 2. Not found scenario
    mock_session.run.return_value.single.return_value = None
    repo_none = retriever.get_repository("repo::missing", session=mock_session)
    assert repo_none is None


def test_get_entity_by_id_various_labels():
    """Verify get_entity_by_id retrieves entities by ID with label-specific lookups."""
    mock_session = MagicMock(spec=Session)
    retriever = GraphRetriever()

    # File lookup
    mock_session.run.return_value.single.return_value = {
        "props": {
            "id": "repo::x::file::foo.py",
            "repo_id": "repo::x",
            "path": "foo.py",
            "language": "python",
            "start_line": 1,
            "end_line": 10,
            "start_byte": 0,
            "end_byte": 50,
        }
    }
    entity = retriever.get_entity_by_id("repo::x::file::foo.py", session=mock_session)
    assert isinstance(entity, File)
    assert entity.id == "repo::x::file::foo.py"
    assert "MATCH (n:File {id: $entity_id})" in mock_session.run.call_args[0][0]

    # Class lookup with repo_id filter
    mock_session.run.return_value.single.return_value = {
        "props": {
            "id": "repo::x::class::foo.Bar",
            "repo_id": "repo::x",
            "name": "Bar",
            "qualified_name": "foo.Bar",
            "file_path": "foo.py",
            "language": "python",
            "start_line": 2,
            "end_line": 8,
            "start_byte": 10,
            "end_byte": 40,
        }
    }
    cls_ent = retriever.get_entity_by_id("repo::x::class::foo.Bar", repo_id="repo::x", session=mock_session)
    assert isinstance(cls_ent, Class)
    assert cls_ent.name == "Bar"
    assert "WHERE ($repo_id IS NULL OR n.repo_id = $repo_id)" in mock_session.run.call_args[0][0]


def test_get_entity_collections_for_repository():
    """Verify retrieval of individual entity collections for a repository."""
    mock_session = MagicMock(spec=Session)
    retriever = GraphRetriever()

    # Mock get_files
    mock_session.run.return_value = [
        {
            "props": {
                "id": "repo::r::file::a.py",
                "repo_id": "repo::r",
                "path": "a.py",
                "language": "python",
                "start_line": 1,
                "end_line": 5,
                "start_byte": 0,
                "end_byte": 30,
            }
        }
    ]
    files = retriever.get_files("repo::r", session=mock_session)
    assert len(files) == 1
    assert files[0].path == "a.py"

    # Mock empty collection
    mock_session.run.return_value = []
    classes = retriever.get_classes("repo::r", session=mock_session)
    assert classes == []


def test_get_relationships_filters_and_repository_isolation():
    """Verify get_relationships applies relationship type and endpoint filters with repo isolation."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value = [
        {
            "source_id": "repo::r::function::f1",
            "target_id": "repo::r::function::f2",
            "rel_type": "CALLS",
            "properties": {"start_line": 4, "end_line": 4},
        }
    ]

    retriever = GraphRetriever()
    rels = retriever.get_relationships(
        "repo::r",
        rel_type=RelationshipType.CALLS,
        source_id="repo::r::function::f1",
        session=mock_session,
    )

    assert len(rels) == 1
    assert rels[0].rel_type == RelationshipType.CALLS
    assert rels[0].source_id == "repo::r::function::f1"
    assert rels[0].target_id == "repo::r::function::f2"

    cypher_called = mock_session.run.call_args[0][0]
    assert "WHERE type(r) = $rel_type" in cypher_called
    assert "src.repo_id = $repo_id" in cypher_called
    assert "tgt.repo_id = $repo_id" in cypher_called
    assert "$source_id IS NULL OR src.id = $source_id" in cypher_called


def test_get_repository_graph_complete_reconstruction():
    """Verify get_repository_graph reconstructs complete UnifiedCodeModel."""
    mock_session = MagicMock(spec=Session)

    repo_record = {"props": {"id": "repo::g", "name": "g", "source": "/src"}}
    file_record = {
        "props": {
            "id": "repo::g::file::x.py",
            "repo_id": "repo::g",
            "path": "x.py",
            "language": "python",
            "start_line": 1,
            "end_line": 10,
            "start_byte": 0,
            "end_byte": 50,
        }
    }
    class_record = {
        "props": {
            "id": "repo::g::class::x.X",
            "repo_id": "repo::g",
            "name": "X",
            "qualified_name": "x.X",
            "file_path": "x.py",
            "language": "python",
            "start_line": 2,
            "end_line": 8,
            "start_byte": 10,
            "end_byte": 40,
        }
    }
    rel_record = {
        "source_id": "repo::g::file::x.py",
        "target_id": "repo::g::class::x.X",
        "rel_type": "CONTAINS",
        "properties": {},
    }

    # Dispatch responses according to query
    def mock_run_dispatcher(query: str, **kwargs):
        mock_res = MagicMock()
        if "MATCH (r:Repository" in query:
            mock_res.single.return_value = repo_record
            mock_res.__iter__.return_value = [repo_record]
        elif "MATCH (n:File" in query:
            mock_res.__iter__.return_value = [file_record]
        elif "MATCH (n:Class" in query:
            mock_res.__iter__.return_value = [class_record]
        elif "MATCH (src)-[r]->(tgt)" in query:
            mock_res.__iter__.return_value = [rel_record]
        else:
            mock_res.__iter__.return_value = []
            mock_res.single.return_value = None
        return mock_res

    mock_session.run.side_effect = mock_run_dispatcher

    ucm = get_repository_graph("repo::g", session=mock_session)

    assert isinstance(ucm, UnifiedCodeModel)
    assert ucm.repository.id == "repo::g"
    assert len(ucm.files) == 1
    assert ucm.files[0].path == "x.py"
    assert len(ucm.classes) == 1
    assert ucm.classes[0].name == "X"
    assert len(ucm.relationships) == 1
    assert ucm.relationships[0].rel_type == RelationshipType.CONTAINS


def test_get_repository_graph_missing_repository_returns_none():
    """Verify missing repository returns None predictably without errors."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = None

    ucm = get_repository_graph("repo::does_not_exist", session=mock_session)
    assert ucm is None


def test_retrieval_queries_are_strictly_read_only():
    """Verify all queries generated during graph retrieval are non-mutating MATCH ... RETURN statements."""
    executed_queries: list[str] = []

    mock_session = MagicMock(spec=Session)

    def record_query(query: str, **kwargs):
        executed_queries.append(query)
        mock_res = MagicMock()
        if "MATCH (r:Repository" in query:
            mock_res.single.return_value = {"props": {"id": "repo::q", "name": "q", "source": "/s"}}
        elif "MATCH (n:File" in query:
            mock_res.single.return_value = {
                "props": {
                    "id": "repo::q::file::a.py",
                    "repo_id": "repo::q",
                    "path": "a.py",
                    "language": "python",
                    "start_line": 1,
                    "end_line": 10,
                }
            }
        else:
            mock_res.single.return_value = None
        mock_res.__iter__.return_value = []
        return mock_res

    mock_session.run.side_effect = record_query

    retriever = GraphRetriever()
    retriever.get_repository_graph("repo::q", session=mock_session)
    retriever.get_entity_by_id("repo::q::file::a.py", session=mock_session)
    retriever.get_relationships("repo::q", session=mock_session)

    forbidden_keywords = {"CREATE", "MERGE", "SET", "DELETE", "REMOVE", "DROP"}
    assert len(executed_queries) >= 8

    for query in executed_queries:
        tokens = query.upper().split()
        for forbidden in forbidden_keywords:
            assert forbidden not in tokens, f"Query contains mutating clause '{forbidden}': {query}"
        assert query.strip().startswith("MATCH"), f"Query must start with MATCH: {query}"


def test_session_lifecycle_caller_owned_session_not_closed():
    """Verify caller-owned session is not closed by the retriever."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = None

    get_entity_by_id("repo::r::file::x.py", session=mock_session)
    assert not mock_session.close.called


def test_session_lifecycle_managed_driver_session_closed():
    """Verify managed session acquired from driver is safely closed."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = None

    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session

    get_entity_by_id("repo::r::file::x.py", driver=mock_driver)
    mock_driver.session.assert_called_once()
    mock_session.close.assert_called_once()


def test_error_handling_masks_credentials():
    """Verify database connection errors mask credentials."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.side_effect = Exception(
        "Connection refused to bolt://neo4j:confidential_pw@neo4j:7687"
    )

    with pytest.raises(Neo4jRetrievalError) as exc_info:
        get_repository_graph("repo::err", session=mock_session)

    assert "confidential_pw" not in str(exc_info.value)
    assert isinstance(exc_info.value, Neo4jConnectionError)


def test_reconstruct_atlas_fixture_graph_from_simulated_records():
    """Verify complete reconstruction of the controlled Atlas fixture graph from simulated database records."""
    resolved_fixture = resolve_repository(repo_path=FIXTURE_DIR, repo_name="atlas_fixture")

    # Serialize resolved entities and relationships as Neo4j property dictionaries
    repo_record = {"props": resolved_fixture.repository.to_dict()}
    file_records = [{"props": f.to_dict()} for f in resolved_fixture.files]
    module_records = [{"props": m.to_dict()} for m in resolved_fixture.modules]
    class_records = [{"props": c.to_dict()} for c in resolved_fixture.classes]
    func_records = [{"props": fn.to_dict()} for fn in resolved_fixture.functions]
    meth_records = [{"props": mt.to_dict()} for mt in resolved_fixture.methods]
    import_records = [{"props": im.to_dict()} for im in resolved_fixture.imports]

    rel_records = []
    for r in resolved_fixture.relationships:
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

    reconstructed_ucm = get_repository_graph(resolved_fixture.repository.id, session=mock_session)

    assert reconstructed_ucm is not None
    assert reconstructed_ucm.repository.id == resolved_fixture.repository.id
    assert len(reconstructed_ucm.files) == len(resolved_fixture.files) == 7
    assert len(reconstructed_ucm.modules) == len(resolved_fixture.modules) == 7
    assert len(reconstructed_ucm.classes) == len(resolved_fixture.classes) == 7
    assert len(reconstructed_ucm.functions) == len(resolved_fixture.functions) == 11
    assert len(reconstructed_ucm.methods) == len(resolved_fixture.methods) == 12
    assert len(reconstructed_ucm.imports) == len(resolved_fixture.imports) == 8
    assert len(reconstructed_ucm.relationships) == len(resolved_fixture.relationships) == 58

    # Verify counts per relationship type match ground truth
    rel_counts = {}
    for r in reconstructed_ucm.relationships:
        rel_counts[r.rel_type] = rel_counts.get(r.rel_type, 0) + 1

    assert rel_counts[RelationshipType.CONTAINS] == 37
    assert rel_counts[RelationshipType.IMPORTS] == 5
    assert rel_counts[RelationshipType.CALLS] == 15
    assert rel_counts[RelationshipType.INHERITS] == 1


def test_neo4j_record_membership_check_discrepancy_and_resolution():
    """Verify the root cause discrepancy: neo4j.Record inherits from tuple, so 'key in record'
    checks tuple elements (values) and returns False, while record.get('key') succeeds.
    """
    props = {"id": "repo::atlas_fixture", "name": "atlas_fixture", "source": "/app"}
    rec = Record([("props", props)])

    # Root cause reproduction: in operator fails because 'props' != props
    assert ("props" in rec) is False
    assert rec.get("props") == props

    # Verify GraphRetriever.get_repository succeeds with Record
    mock_session = MagicMock(spec=Session)
    mock_session.run.return_value.single.return_value = rec
    retriever = GraphRetriever()
    repo = retriever.get_repository("repo::atlas_fixture", session=mock_session)
    assert isinstance(repo, Repository)
    assert repo.id == "repo::atlas_fixture"


def test_get_repository_graph_with_real_neo4j_record_instances():
    """Verify GraphRetriever reconstructs the complete UCM when driver returns real neo4j.Record objects."""
    resolved_fixture = resolve_repository(repo_path=FIXTURE_DIR, repo_name="atlas_fixture")
    repo_rec = Record([("props", resolved_fixture.repository.to_dict())])
    file_recs = [Record([("props", f.to_dict())]) for f in resolved_fixture.files]
    module_recs = [Record([("props", m.to_dict())]) for m in resolved_fixture.modules]
    class_recs = [Record([("props", c.to_dict())]) for c in resolved_fixture.classes]
    func_recs = [Record([("props", fn.to_dict())]) for fn in resolved_fixture.functions]
    meth_recs = [Record([("props", mt.to_dict())]) for mt in resolved_fixture.methods]
    import_recs = [Record([("props", im.to_dict())]) for im in resolved_fixture.imports]

    rel_recs = []
    for r in resolved_fixture.relationships:
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

    retriever = GraphRetriever()
    ucm = retriever.get_repository_graph(resolved_fixture.repository.id, session=mock_session)

    assert ucm is not None
    assert ucm.repository.id == resolved_fixture.repository.id
    assert len(ucm.files) == 7
    assert len(ucm.modules) == 7
    assert len(ucm.classes) == 7
    assert len(ucm.functions) == 11
    assert len(ucm.methods) == 12
    assert len(ucm.imports) == 8
    assert len(ucm.relationships) == 58


def test_get_entity_by_id_with_neo4j_record():
    """Verify get_entity_by_id functions correctly with real neo4j.Record instances."""
    mock_session = MagicMock(spec=Session)
    retriever = GraphRetriever()

    # Specific label File lookup
    file_props = {
        "id": "repo::x::file::foo.py",
        "repo_id": "repo::x",
        "path": "foo.py",
        "language": "python",
        "start_line": 1,
        "end_line": 10,
        "start_byte": 0,
        "end_byte": 50,
    }
    mock_session.run.return_value.single.return_value = Record([("props", file_props)])
    entity = retriever.get_entity_by_id("repo::x::file::foo.py", session=mock_session)
    assert isinstance(entity, File)
    assert entity.id == "repo::x::file::foo.py"

    # Multi-label dynamic lookup
    fn_props = {
        "id": "custom::fn",
        "repo_id": "repo::x",
        "name": "my_fn",
        "qualified_name": "my_fn",
        "file_path": "foo.py",
        "language": "python",
        "start_line": 2,
        "end_line": 5,
        "start_byte": 10,
        "end_byte": 30,
    }
    mock_session.run.return_value.single.return_value = Record(
        [
            ("props", fn_props),
            ("labels", ["Function", "Custom"]),
        ]
    )
    custom_entity = retriever.get_entity_by_id("custom::fn", session=mock_session)
    assert isinstance(custom_entity, Function)
    assert custom_entity.name == "my_fn"

