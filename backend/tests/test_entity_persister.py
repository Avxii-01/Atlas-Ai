"""Automated tests for Neo4j UCM entity persistence, transactions, and repository isolation."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest
from neo4j import Driver, Session

from app.db.entity_persister import (
    EntityPersistenceResult,
    EntityPersister,
    Neo4jPersistenceError,
    entity_to_properties,
    get_entity_merge_cypher,
    persist_entities,
)
from app.db.neo4j import Neo4jConnectionError, set_driver
from app.db.schema import NodeLabel
from app.extractor.python_extractor import extract_python_repository
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

FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "atlas_fixture"


@pytest.fixture(autouse=True)
def reset_driver_state():
    """Ensure driver state is reset before and after every test."""
    set_driver(None)
    yield
    set_driver(None)


def _create_sample_ucm(repo_name: str = "test_repo") -> UnifiedCodeModel:
    """Helper creating a minimal valid UCM with all 7 entity types."""
    repo = Repository.create(name=repo_name, source="/path/to/repo", created_at="2026-10-09T00:00:00Z")
    repo_id = repo.id

    file_ent = File.create(
        repo_id=repo_id,
        path="services/item.py",
        end_line=50,
        start_line=1,
        start_byte=0,
        end_byte=1000,
    )
    module_ent = Module.create(
        repo_id=repo_id,
        name="item",
        qualified_name="services.item",
        file_path="services/item.py",
    )
    class_ent = Class.create(
        repo_id=repo_id,
        name="ItemService",
        qualified_name="services.item.ItemService",
        file_path="services/item.py",
        start_line=10,
        end_line=30,
        start_byte=200,
        end_byte=600,
        docstring="Item management service.",
    )
    func_ent = Function.create(
        repo_id=repo_id,
        name="create_item",
        qualified_name="services.item.create_item",
        file_path="services/item.py",
        start_line=35,
        end_line=45,
        start_byte=700,
        end_byte=950,
        docstring="Standalone factory.",
    )
    method_ent = Method.create(
        repo_id=repo_id,
        name="get_item",
        qualified_name="services.item.ItemService.get_item",
        file_path="services/item.py",
        start_line=15,
        end_line=25,
        start_byte=300,
        end_byte=500,
        docstring=None,
    )
    import_ent = Import.create(
        repo_id=repo_id,
        file_path="services/item.py",
        module_name="models",
        imported_name="ItemModel",
        start_line=3,
        end_line=3,
        alias="Model",
        start_byte=40,
        end_byte=80,
    )

    ucm = UnifiedCodeModel(repository=repo)
    ucm.add_file(file_ent)
    ucm.add_module(module_ent)
    ucm.add_class(class_ent)
    ucm.add_function(func_ent)
    ucm.add_method(method_ent)
    ucm.add_import(import_ent)
    return ucm


def test_entity_to_properties_mapping_all_types():
    """Verify entity_to_properties correctly maps properties and strips None values."""
    repo = Repository.create(name="demo", source="/src", created_at=None)
    repo_props = entity_to_properties(repo)
    assert repo_props == {"id": repo.id, "name": "demo", "source": "/src"}
    assert "created_at" not in repo_props

    file_ent = File.create(repo_id=repo.id, path="a.py", end_line=10, start_line=1, start_byte=0, end_byte=100)
    file_props = entity_to_properties(file_ent)
    assert file_props == {
        "id": file_ent.id,
        "repo_id": repo.id,
        "path": "a.py",
        "language": "python",
        "start_line": 1,
        "end_line": 10,
        "start_byte": 0,
        "end_byte": 100,
    }

    class_ent = Class.create(
        repo_id=repo.id,
        name="Foo",
        qualified_name="a.Foo",
        file_path="a.py",
        start_line=2,
        end_line=8,
        start_byte=15,
        end_byte=80,
        docstring="Docstring text",
    )
    class_props = entity_to_properties(class_ent)
    assert class_props["docstring"] == "Docstring text"
    assert class_props["qualified_name"] == "a.Foo"

    class_no_doc = Class.create(
        repo_id=repo.id,
        name="Bar",
        qualified_name="a.Bar",
        file_path="a.py",
        start_line=2,
        end_line=8,
        start_byte=15,
        end_byte=80,
        docstring=None,
    )
    class_no_doc_props = entity_to_properties(class_no_doc)
    assert "docstring" not in class_no_doc_props

    import_ent = Import.create(
        repo_id=repo.id,
        file_path="a.py",
        module_name="os",
        imported_name="path",
        start_line=1,
        end_line=1,
        alias=None,
    )
    import_props = entity_to_properties(import_ent)
    assert "alias" not in import_props


def test_get_entity_merge_cypher():
    """Verify parameterized MERGE Cypher for each node label."""
    for label in NodeLabel:
        cypher = get_entity_merge_cypher(label)
        assert f"MERGE (n:{label.value} {{id: props.id}})" in cypher
        assert "UNWIND $batch AS props" in cypher
        assert "SET n += props" in cypher


def test_persist_repository_entity():
    """Verify persisting a Repository entity executes expected Cypher and batch."""
    repo = Repository.create(name="alpha", source="/src", created_at="2026-10-09T00:00:00Z")
    mock_session = MagicMock(spec=Session)

    persister = EntityPersister()
    count = persister.persist_repository(repo, session=mock_session)

    assert count == 1
    mock_session.run.assert_called_once()
    cypher_called, kwargs_called = mock_session.run.call_args[0][0], mock_session.run.call_args[1]

    assert "MERGE (n:Repository {id: props.id})" in cypher_called
    batch = kwargs_called["batch"]
    assert len(batch) == 1
    assert batch[0]["id"] == repo.id
    assert batch[0]["name"] == "alpha"
    assert batch[0]["created_at"] == "2026-10-09T00:00:00Z"


def test_persist_file_and_module_entities():
    """Verify persisting File and Module entity batches."""
    repo_id = "repo::test"
    files = [
        File.create(repo_id=repo_id, path="mod1.py", end_line=10),
        File.create(repo_id=repo_id, path="mod2.py", end_line=20),
    ]
    modules = [
        Module.create(repo_id=repo_id, name="mod1", qualified_name="mod1", file_path="mod1.py"),
        Module.create(repo_id=repo_id, name="mod2", qualified_name="mod2", file_path="mod2.py"),
    ]

    mock_session = MagicMock(spec=Session)
    persister = EntityPersister()

    files_count = persister.persist_files(files, session=mock_session)
    modules_count = persister.persist_modules(modules, session=mock_session)

    assert files_count == 2
    assert modules_count == 2
    assert mock_session.run.call_count == 2

    first_call_cypher = mock_session.run.call_args_list[0][0][0]
    assert "MERGE (n:File {id: props.id})" in first_call_cypher

    second_call_cypher = mock_session.run.call_args_list[1][0][0]
    assert "MERGE (n:Module {id: props.id})" in second_call_cypher


def test_persist_class_function_and_method_entities():
    """Verify persisting Class, Function, and Method entities."""
    repo_id = "repo::test"
    classes = [
        Class.create(
            repo_id=repo_id,
            name="C1",
            qualified_name="pkg.C1",
            file_path="pkg/c.py",
            start_line=1,
            end_line=10,
            start_byte=0,
            end_byte=100,
        )
    ]
    functions = [
        Function.create(
            repo_id=repo_id,
            name="f1",
            qualified_name="pkg.f1",
            file_path="pkg/f.py",
            start_line=1,
            end_line=5,
            start_byte=0,
            end_byte=50,
        )
    ]
    methods = [
        Method.create(
            repo_id=repo_id,
            name="m1",
            qualified_name="pkg.C1.m1",
            file_path="pkg/c.py",
            start_line=3,
            end_line=6,
            start_byte=20,
            end_byte=60,
        )
    ]

    mock_session = MagicMock(spec=Session)
    persister = EntityPersister()

    assert persister.persist_classes(classes, session=mock_session) == 1
    assert persister.persist_functions(functions, session=mock_session) == 1
    assert persister.persist_methods(methods, session=mock_session) == 1

    assert mock_session.run.call_count == 3


def test_persist_import_entities():
    """Verify persisting Import entities preserves aliases and line positions."""
    repo_id = "repo::test"
    imports = [
        Import.create(
            repo_id=repo_id,
            file_path="app.py",
            module_name="services",
            imported_name="ItemService",
            start_line=2,
            end_line=2,
            alias="Svc",
        ),
        Import.create(
            repo_id=repo_id,
            file_path="app.py",
            module_name="utils",
            imported_name="helper",
            start_line=3,
            end_line=3,
            alias=None,
        ),
    ]

    mock_session = MagicMock(spec=Session)
    persister = EntityPersister()
    count = persister.persist_imports(imports, session=mock_session)

    assert count == 2
    mock_session.run.assert_called_once()
    kwargs = mock_session.run.call_args[1]
    batch = kwargs["batch"]
    assert len(batch) == 2
    assert batch[0]["alias"] == "Svc"
    assert "alias" not in batch[1]


def test_persist_unified_code_model_atomic_transaction():
    """Verify persisting a complete UCM runs within a transaction and commits."""
    ucm = _create_sample_ucm("unified_repo")

    mock_tx = MagicMock()
    mock_session = MagicMock(spec=Session)
    mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx

    result = persist_entities(ucm, session=mock_session)

    assert isinstance(result, EntityPersistenceResult)
    assert result.repository_id == ucm.repository.id
    assert result.total_entities == 7  # 1 repo + 1 file + 1 module + 1 class + 1 func + 1 meth + 1 import

    assert result.get_count(NodeLabel.REPOSITORY) == 1
    assert result.get_count(NodeLabel.FILE) == 1
    assert result.get_count(NodeLabel.MODULE) == 1
    assert result.get_count(NodeLabel.CLASS) == 1
    assert result.get_count(NodeLabel.FUNCTION) == 1
    assert result.get_count(NodeLabel.METHOD) == 1
    assert result.get_count(NodeLabel.IMPORT) == 1

    # Verify tx.run called 7 times (for the 7 non-empty batches)
    assert mock_tx.run.call_count == 7
    mock_tx.commit.assert_called_once()


def test_reingestion_idempotence_and_no_duplicates():
    """Verify re-ingesting the exact same UCM executes identical queries with MERGE."""
    ucm = _create_sample_ucm("reingest_repo")

    mock_tx1 = MagicMock()
    mock_session1 = MagicMock(spec=Session)
    mock_session1.begin_transaction.return_value.__enter__.return_value = mock_tx1

    result1 = persist_entities(ucm, session=mock_session1)

    mock_tx2 = MagicMock()
    mock_session2 = MagicMock(spec=Session)
    mock_session2.begin_transaction.return_value.__enter__.return_value = mock_tx2

    result2 = persist_entities(ucm, session=mock_session2)

    assert result1 == result2

    # Assert that all queries executed across both runs use MERGE on id
    for mock_tx in (mock_tx1, mock_tx2):
        for call_item in mock_tx.run.call_args_list:
            cypher = call_item[0][0]
            assert "MERGE (n:" in cypher
            assert "{id: props.id}" in cypher
            assert "CREATE (n:" not in cypher  # Must NOT use unconstrained CREATE


def test_repository_isolation():
    """Verify entities from two distinct repositories have disjoint IDs and do not collide."""
    ucm_a = _create_sample_ucm("repo_alpha")
    ucm_b = _create_sample_ucm("repo_beta")

    mock_tx_a = MagicMock()
    mock_session_a = MagicMock(spec=Session)
    mock_session_a.begin_transaction.return_value.__enter__.return_value = mock_tx_a

    persist_entities(ucm_a, session=mock_session_a)

    mock_tx_b = MagicMock()
    mock_session_b = MagicMock(spec=Session)
    mock_session_b.begin_transaction.return_value.__enter__.return_value = mock_tx_b

    persist_entities(ucm_b, session=mock_session_b)

    # Extract all persisted entity IDs for repo A and repo B
    ids_a = {
        item["id"]
        for call_item in mock_tx_a.run.call_args_list
        for item in call_item[1]["batch"]
    }
    ids_b = {
        item["id"]
        for call_item in mock_tx_b.run.call_args_list
        for item in call_item[1]["batch"]
    }

    # Repository isolation: IDs must be strictly disjoint
    assert ids_a.isdisjoint(ids_b)

    for entity_id in ids_a:
        assert "repo::repo_alpha" in entity_id
    for entity_id in ids_b:
        assert "repo::repo_beta" in entity_id


def test_persist_representative_entities_from_atlas_fixture():
    """Verify persistence of entities extracted from the controlled Atlas fixture."""
    ucm = extract_python_repository(repo_path=FIXTURE_DIR, repo_name="atlas_fixture")

    mock_tx = MagicMock()
    mock_session = MagicMock(spec=Session)
    mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx

    result = persist_entities(ucm, session=mock_session)

    # Verify fixture ground-truth counts
    assert result.get_count(NodeLabel.REPOSITORY) == 1
    assert result.get_count(NodeLabel.FILE) == len(ucm.files)
    assert result.get_count(NodeLabel.MODULE) == len(ucm.modules)
    assert result.get_count(NodeLabel.CLASS) == len(ucm.classes)
    assert result.get_count(NodeLabel.FUNCTION) == len(ucm.functions)
    assert result.get_count(NodeLabel.METHOD) == len(ucm.methods)
    assert result.get_count(NodeLabel.IMPORT) == len(ucm.imports)

    assert result.total_entities == 53
    mock_tx.commit.assert_called_once()

    # Verify that properties in batches conform to expectations
    persisted_batches = {
        call_item[0][0].split("MERGE (n:")[1].split(" ")[0]: call_item[1]["batch"]
        for call_item in mock_tx.run.call_args_list
    }

    file_paths = {item["path"] for item in persisted_batches["File"]}
    assert "app.py" in file_paths
    assert "services.py" in file_paths
    assert "models.py" in file_paths
    assert "unrelated.py" in file_paths

    class_names = {item["name"] for item in persisted_batches["Class"]}
    assert "ItemService" in class_names
    assert "ItemModel" in class_names
    assert "BaseEntity" in class_names
    assert "StandaloneCalculator" in class_names


def test_transaction_rollback_on_execution_failure():
    """Verify transaction failure raises Neo4jPersistenceError and does not commit."""
    ucm = _create_sample_ucm("faulty_repo")

    mock_tx = MagicMock()
    mock_tx.run.side_effect = Exception("Fatal database deadlock")
    mock_session = MagicMock(spec=Session)
    mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx

    with pytest.raises(Neo4jPersistenceError, match="Failed to persist entities"):
        persist_entities(ucm, session=mock_session)

    mock_tx.commit.assert_not_called()


def test_session_lifecycle_caller_owned_session_not_closed():
    """Verify caller-owned session is not closed by the persister."""
    ucm = _create_sample_ucm("session_check")

    mock_tx = MagicMock()
    mock_session = MagicMock(spec=Session)
    mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx

    persist_entities(ucm, session=mock_session)
    assert not mock_session.close.called


def test_session_lifecycle_managed_driver_session_closed():
    """Verify persister-created session is acquired from driver and closed."""
    ucm = _create_sample_ucm("driver_session_check")

    mock_tx = MagicMock()
    mock_session = MagicMock(spec=Session)
    mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx

    mock_session_cm = MagicMock()
    mock_session_cm.__enter__.return_value = mock_session

    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session_cm

    result = persist_entities(ucm, driver=mock_driver)
    assert result.total_entities == 7

    mock_driver.session.assert_called_once()
    mock_session_cm.__exit__.assert_called_once()


def test_error_handling_masks_sensitive_credentials():
    """Verify persistence errors do not leak database credentials."""
    ucm = _create_sample_ucm("secret_check")

    mock_tx = MagicMock()
    mock_tx.run.side_effect = Exception(
        "Connection lost to bolt://neo4j:super_secret_password_token@neo4j:7687"
    )
    mock_session = MagicMock(spec=Session)
    mock_session.begin_transaction.return_value.__enter__.return_value = mock_tx

    with pytest.raises(Neo4jPersistenceError) as exc_info:
        persist_entities(ucm, session=mock_session)

    assert "super_secret_password_token" not in str(exc_info.value)
    assert isinstance(exc_info.value, Neo4jConnectionError)


def test_uninitialized_driver_raises_persistence_error():
    """Verify persisting without driver or session raises Neo4jPersistenceError."""
    ucm = _create_sample_ucm("no_driver")

    with pytest.raises(Neo4jPersistenceError, match="Failed to acquire Neo4j driver"):
        persist_entities(ucm)
