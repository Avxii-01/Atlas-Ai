"""Automated tests for Neo4j UCM relationship persistence, direction, endpoint safety, and repository isolation."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest
from neo4j import Driver, Session

from app.db.neo4j import Neo4jConnectionError, set_driver
from app.db.relationship_persister import (
    Neo4jRelationshipPersistenceError,
    RelationshipPersistenceResult,
    RelationshipPersister,
    get_relationship_merge_cypher,
    label_from_entity_id,
    persist_relationships,
    relationship_to_properties,
    repo_id_from_entity_id,
)
from app.db.schema import NodeLabel
from app.parser.models import SourcePosition, SourceRange
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
from app.ucm.relationships import (
    Relationship,
    RelationshipType,
    create_calls_rel,
    create_contains_rel,
    create_imports_rel,
    create_inherits_rel,
)

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "atlas_fixture"


@pytest.fixture(autouse=True)
def reset_driver_state():
    """Ensure driver state is reset before and after every test."""
    set_driver(None)
    yield
    set_driver(None)


def _create_sample_ucm_with_relationships(repo_name: str = "test_repo") -> UnifiedCodeModel:
    """Helper creating a sample UCM with entities and all 4 relationship types."""
    repo = Repository.create(name=repo_name, source="/src")
    repo_id = repo.id

    file1 = File.create(repo_id=repo_id, path="app.py", end_line=50)
    file2 = File.create(repo_id=repo_id, path="services.py", end_line=60)
    mod2 = Module.create(repo_id=repo_id, name="services", qualified_name="services", file_path="services.py")

    cls1 = Class.create(
        repo_id=repo_id,
        name="BaseService",
        qualified_name="services.BaseService",
        file_path="services.py",
        start_line=5,
        end_line=20,
        start_byte=50,
        end_byte=200,
    )
    cls2 = Class.create(
        repo_id=repo_id,
        name="SubService",
        qualified_name="services.SubService",
        file_path="services.py",
        start_line=22,
        end_line=45,
        start_byte=220,
        end_byte=450,
    )
    meth1 = Method.create(
        repo_id=repo_id,
        name="execute",
        qualified_name="services.SubService.execute",
        file_path="services.py",
        start_line=25,
        end_line=30,
        start_byte=250,
        end_byte=300,
    )
    func1 = Function.create(
        repo_id=repo_id,
        name="main",
        qualified_name="app.main",
        file_path="app.py",
        start_line=10,
        end_line=20,
        start_byte=100,
        end_byte=200,
    )

    loc = SourceRange(
        start_point=SourcePosition(line=12, column=4),
        end_point=SourcePosition(line=12, column=24),
        start_byte=120,
        end_byte=140,
    )

    ucm = UnifiedCodeModel(repository=repo)
    for f in (file1, file2):
        ucm.add_file(f)
    ucm.add_module(mod2)
    for c in (cls1, cls2):
        ucm.add_class(c)
    ucm.add_method(meth1)
    ucm.add_function(func1)

    # 1. CONTAINS: Repo -> File, File -> Class, Class -> Method
    ucm.add_relationship(create_contains_rel(repo.id, file1.id))
    ucm.add_relationship(create_contains_rel(file2.id, cls2.id))
    ucm.add_relationship(create_contains_rel(cls2.id, meth1.id))

    # 2. IMPORTS: File -> Module
    ucm.add_relationship(create_imports_rel(file1.id, mod2.id, location=loc, metadata={"alias": "srv"}))

    # 3. CALLS: Function -> Method
    ucm.add_relationship(create_calls_rel(func1.id, meth1.id, location=loc))

    # 4. INHERITS: Class -> Class
    ucm.add_relationship(create_inherits_rel(cls2.id, cls1.id))

    return ucm


def test_label_and_repo_id_from_entity_id():
    """Verify entity ID parsing functions accurately extract labels and repo IDs."""
    repo_id = "repo::atlas"
    assert label_from_entity_id(repo_id) == "Repository"
    assert repo_id_from_entity_id(repo_id) == repo_id

    file_id = f"{repo_id}::file::services.py"
    assert label_from_entity_id(file_id) == "File"
    assert repo_id_from_entity_id(file_id) == repo_id

    class_id = f"{repo_id}::class::services.ItemService"
    assert label_from_entity_id(class_id) == "Class"
    assert repo_id_from_entity_id(class_id) == repo_id

    func_id = f"{repo_id}::function::app.main"
    assert label_from_entity_id(func_id) == "Function"
    assert repo_id_from_entity_id(func_id) == repo_id

    meth_id = f"{repo_id}::method::services.ItemService.run"
    assert label_from_entity_id(meth_id) == "Method"
    assert repo_id_from_entity_id(meth_id) == repo_id

    import_id = f"{repo_id}::import::app.py::L3::ItemService"
    assert label_from_entity_id(import_id) == "Import"
    assert repo_id_from_entity_id(import_id) == repo_id

    assert label_from_entity_id("invalid_id") is None
    assert repo_id_from_entity_id("invalid_id") is None


def test_relationship_to_properties_location_and_metadata():
    """Verify evidence source range and metadata conversion to properties."""
    loc = SourceRange(
        start_point=SourcePosition(line=10, column=5),
        end_point=SourcePosition(line=10, column=25),
        start_byte=100,
        end_byte=120,
    )
    rel_with_loc = create_calls_rel(
        source_id="repo::a::function::foo",
        target_id="repo::a::function::bar",
        location=loc,
        metadata={"call_expr": "bar()", "arg_count": 0},
    )

    props = relationship_to_properties(rel_with_loc)
    assert props["start_line"] == 10
    assert props["start_column"] == 5
    assert props["end_line"] == 10
    assert props["end_column"] == 25
    assert props["start_byte"] == 100
    assert props["end_byte"] == 120
    assert props["call_expr"] == "bar()"
    assert props["arg_count"] == 0

    rel_no_loc = create_inherits_rel("repo::a::class::C1", "repo::a::class::C2")
    assert relationship_to_properties(rel_no_loc) == {}


def test_get_relationship_merge_cypher_structure():
    """Verify generated Cypher preserves direction, endpoint matching, and repo isolation."""
    cypher = get_relationship_merge_cypher("CONTAINS", "Repository", "File")
    assert "MATCH (src:Repository {id: rel.source_id})" in cypher
    assert "MATCH (tgt:File {id: rel.target_id})" in cypher
    assert "MERGE (src)-[r:CONTAINS]->(tgt)" in cypher
    assert "SET r += rel.properties" in cypher
    assert "RETURN count(r) AS persisted_count" in cypher

    # Verify Calls Cypher
    calls_cypher = get_relationship_merge_cypher("CALLS", "Function", "Method")
    assert "MATCH (src:Function {id: rel.source_id})" in calls_cypher
    assert "MATCH (tgt:Method {id: rel.target_id})" in calls_cypher
    assert "MERGE (src)-[r:CALLS]->(tgt)" in calls_cypher
    assert "WHERE src.repo_id = $repo_id" in calls_cypher
    assert "WHERE tgt.repo_id = $repo_id" in calls_cypher


def test_persist_all_relationship_types_in_transaction():
    """Verify persisting a UCM commits all 4 relationship types in an atomic transaction."""
    ucm = _create_sample_ucm_with_relationships("sample_rel_repo")

    mock_tx = MagicMock()
    mock_session = MagicMock(spec=Session)
    mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx

    result = persist_relationships(ucm, session=mock_session)

    assert isinstance(result, RelationshipPersistenceResult)
    assert result.repository_id == ucm.repository.id

    assert result.get_persisted_count(RelationshipType.CONTAINS) == 3
    assert result.get_persisted_count(RelationshipType.IMPORTS) == 1
    assert result.get_persisted_count(RelationshipType.CALLS) == 1
    assert result.get_persisted_count(RelationshipType.INHERITS) == 1

    assert result.total_persisted == 6
    assert result.total_skipped == 0
    mock_tx.commit.assert_called_once()


def test_reingestion_idempotence_and_no_duplicate_relationships():
    """Verify repeatedly persisting the same relationships executes identical MERGE queries."""
    ucm = _create_sample_ucm_with_relationships("idempotent_repo")

    mock_tx1 = MagicMock()
    mock_session1 = MagicMock(spec=Session)
    mock_session1.begin_transaction.return_value.__enter__.return_value = mock_tx1

    result1 = persist_relationships(ucm, session=mock_session1)

    mock_tx2 = MagicMock()
    mock_session2 = MagicMock(spec=Session)
    mock_session2.begin_transaction.return_value.__enter__.return_value = mock_tx2

    result2 = persist_relationships(ucm, session=mock_session2)

    assert result1 == result2

    # Verify that all Cypher statements executed across runs use MERGE (src)-[r:...]->(tgt)
    for mock_tx in (mock_tx1, mock_tx2):
        for call_item in mock_tx.run.call_args_list:
            cypher = call_item[0][0]
            assert "MERGE (src)-[r:" in cypher
            assert "CREATE (src)-[r:" not in cypher  # Must never use non-idempotent CREATE edge


def test_missing_endpoints_handled_safely_no_side_effects():
    """Verify missing endpoints are skipped safely without creating fake nodes."""
    ucm = _create_sample_ucm_with_relationships("missing_endpoint_repo")

    # Add a relationship whose target does not exist in the UCM
    bad_rel = create_calls_rel(
        source_id=f"{ucm.repository.id}::function::app.main",
        target_id=f"{ucm.repository.id}::function::missing.nonexistent_function",
    )
    ucm.add_relationship(bad_rel)

    mock_tx = MagicMock()
    mock_session = MagicMock(spec=Session)
    mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx

    result = persist_relationships(ucm, session=mock_session)

    # 1 CALLS relationship succeeded (func1 -> meth1), 1 was skipped (bad_rel)
    assert result.get_persisted_count(RelationshipType.CALLS) == 1
    assert result.get_skipped_count(RelationshipType.CALLS) == 1
    assert result.total_skipped == 1


def test_missing_endpoints_in_database_observable_and_skipped():
    """Verify relationships whose endpoints are missing in Neo4j are observed and recorded as skipped."""
    ucm = _create_sample_ucm_with_relationships("db_missing_repo")

    mock_tx = MagicMock()
    mock_session = MagicMock(spec=Session)
    mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx

    # Simulate database returning 0 matches for tx.run because an endpoint did not exist
    mock_record = {"persisted_count": 0}
    mock_result = MagicMock()
    mock_result.single.return_value = mock_record
    mock_tx.run.return_value = mock_result

    result = persist_relationships(ucm, session=mock_session)

    # All relationships in batches were run, but database matched 0
    assert result.total_persisted == 0
    assert result.total_skipped == 6


def test_repository_isolation_enforcement():
    """Verify relationships connecting different repositories are strictly rejected."""
    repo_a = "repo::repo_alpha"
    repo_b = "repo::repo_beta"

    cross_rel = create_calls_rel(
        source_id=f"{repo_a}::function::mod.foo",
        target_id=f"{repo_b}::function::mod.bar",
    )

    mock_tx = MagicMock()
    mock_session = MagicMock(spec=Session)
    mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx

    persister = RelationshipPersister()
    result = persister.persist_relationships([cross_rel], repo_id=repo_a, session=mock_session)

    assert result.total_persisted == 0
    assert result.total_skipped == 1
    assert result.get_skipped_count(RelationshipType.CALLS) == 1

    # tx.run should not have been called because batch was empty
    assert mock_tx.run.call_count == 0


def test_undocumented_relationship_patterns_rejected():
    """Verify invalid/undocumented relationship patterns (e.g. CONTAINS -> Module) are rejected."""
    repo_id = "repo::pattern_check"

    # CONTAINS from File to Module is strictly forbidden by schema
    invalid_rel = create_contains_rel(
        source_id=f"{repo_id}::file::a.py",
        target_id=f"{repo_id}::module::b",
    )

    mock_tx = MagicMock()
    mock_session = MagicMock(spec=Session)
    mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx

    persister = RelationshipPersister()
    result = persister.persist_relationships([invalid_rel], repo_id=repo_id, session=mock_session)

    assert result.total_persisted == 0
    assert result.total_skipped == 1
    assert result.get_skipped_count(RelationshipType.CONTAINS) == 1


def test_persist_atlas_fixture_ground_truth_relationships():
    """Verify persistence of all 58 relationships from the controlled Atlas fixture."""
    resolved_ucm = resolve_repository(repo_path=FIXTURE_DIR, repo_name="atlas_fixture")
    assert len(resolved_ucm.relationships) == 58

    mock_tx = MagicMock()
    mock_session = MagicMock(spec=Session)
    mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx

    result = persist_relationships(resolved_ucm, session=mock_session)

    # Documented fixture ground-truth counts
    assert result.get_persisted_count(RelationshipType.CONTAINS) == 37
    assert result.get_persisted_count(RelationshipType.IMPORTS) == 5
    assert result.get_persisted_count(RelationshipType.CALLS) == 15
    assert result.get_persisted_count(RelationshipType.INHERITS) == 1

    assert result.total_persisted == 58
    assert result.total_skipped == 0
    mock_tx.commit.assert_called_once()

    # Verify query statements were generated for all valid fixture patterns
    cyphers_executed = [call_item[0][0] for call_item in mock_tx.run.call_args_list]
    assert any("MERGE (src)-[r:CONTAINS]->(tgt)" in c for c in cyphers_executed)
    assert any("MERGE (src)-[r:IMPORTS]->(tgt)" in c for c in cyphers_executed)
    assert any("MERGE (src)-[r:CALLS]->(tgt)" in c for c in cyphers_executed)
    assert any("MERGE (src)-[r:INHERITS]->(tgt)" in c for c in cyphers_executed)


def test_session_lifecycle_caller_owned_session_not_closed():
    """Verify caller-owned session is not closed by the relationship persister."""
    ucm = _create_sample_ucm_with_relationships("caller_session_test")

    mock_tx = MagicMock()
    mock_session = MagicMock(spec=Session)
    mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx

    persist_relationships(ucm, session=mock_session)
    assert not mock_session.close.called


def test_session_lifecycle_managed_driver_session_closed():
    """Verify persister-created session from driver is closed via context manager."""
    ucm = _create_sample_ucm_with_relationships("managed_driver_test")

    mock_tx = MagicMock()
    mock_session = MagicMock(spec=Session)
    mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx

    mock_session_cm = MagicMock()
    mock_session_cm.__enter__.return_value = mock_session

    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session_cm

    result = persist_relationships(ucm, driver=mock_driver)
    assert result.total_persisted == 6

    mock_driver.session.assert_called_once()
    mock_session_cm.__exit__.assert_called_once()


def test_error_handling_masks_credentials():
    """Verify transaction errors do not leak database credentials."""
    ucm = _create_sample_ucm_with_relationships("security_check")

    mock_tx = MagicMock()
    mock_tx.run.side_effect = Exception(
        "Connection refused to bolt://neo4j:classified_token@neo4j:7687"
    )
    mock_session = MagicMock(spec=Session)
    mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx

    with pytest.raises(Neo4jRelationshipPersistenceError) as exc_info:
        persist_relationships(ucm, session=mock_session)

    assert "classified_token" not in str(exc_info.value)
    assert isinstance(exc_info.value, Neo4jConnectionError)


def test_uninitialized_driver_raises_error():
    """Verify persistence without driver or session raises Neo4jRelationshipPersistenceError."""
    ucm = _create_sample_ucm_with_relationships("no_driver_test")

    with pytest.raises(Neo4jRelationshipPersistenceError, match="Failed to acquire Neo4j driver"):
        persist_relationships(ucm)
