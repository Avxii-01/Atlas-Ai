"""Automated tests for Neo4j P0 graph schema definitions, constraints, indexes, and initialization."""

from unittest.mock import MagicMock
import pytest
from neo4j import Driver, Session

from app.db.neo4j import Neo4jConnectionError, set_driver
from app.db.schema import (
    NODE_SCHEMAS,
    P0_CONSTRAINTS,
    P0_INDEXES,
    RELATIONSHIP_PATTERNS,
    ConstraintDefinition,
    IndexDefinition,
    Neo4jSchemaError,
    NodeLabel,
    RelationshipType,
    get_all_schema_statements,
    get_constraint_statements,
    get_index_statements,
    get_schema_constraints,
    get_schema_indexes,
    init_schema,
)


@pytest.fixture(autouse=True)
def reset_driver_state():
    """Ensure driver state is reset before and after every test."""
    set_driver(None)
    yield
    set_driver(None)


def test_node_labels_and_schemas_conform_to_contract():
    """Verify all 7 P0 node labels are defined and match docs/GRAPH_SCHEMA.md."""
    expected_labels = {
        "Repository",
        "File",
        "Module",
        "Class",
        "Function",
        "Method",
        "Import",
    }
    actual_labels = {lbl.value for lbl in NodeLabel}
    assert actual_labels == expected_labels

    # Validate Repository schema
    repo_schema = NODE_SCHEMAS[NodeLabel.REPOSITORY]
    assert "id" in repo_schema.required_properties
    assert "name" in repo_schema.required_properties
    assert "source" in repo_schema.required_properties
    assert "created_at" in repo_schema.optional_properties

    # Validate File schema
    file_schema = NODE_SCHEMAS[NodeLabel.FILE]
    assert {"id", "repo_id", "path", "language", "start_line", "end_line"}.issubset(
        file_schema.required_properties
    )
    assert {"start_byte", "end_byte"}.issubset(file_schema.optional_properties)

    # Validate Module schema (respects file_path property to file)
    module_schema = NODE_SCHEMAS[NodeLabel.MODULE]
    assert {"id", "repo_id", "name", "qualified_name", "file_path"}.issubset(
        module_schema.required_properties
    )

    # Validate Class, Function, Method schemas
    for lbl in (NodeLabel.CLASS, NodeLabel.FUNCTION, NodeLabel.METHOD):
        schema = NODE_SCHEMAS[lbl]
        assert {
            "id",
            "repo_id",
            "name",
            "qualified_name",
            "file_path",
            "language",
            "start_line",
            "end_line",
        }.issubset(schema.required_properties)
        assert {"start_byte", "end_byte"}.issubset(schema.optional_properties)

    # Validate Import schema (preserves file_path, imported_name, module_name)
    import_schema = NODE_SCHEMAS[NodeLabel.IMPORT]
    assert {
        "id",
        "repo_id",
        "file_path",
        "module_name",
        "imported_name",
        "start_line",
        "end_line",
    }.issubset(import_schema.required_properties)
    assert {"alias", "start_byte", "end_byte"}.issubset(import_schema.optional_properties)


def test_relationship_patterns_conform_to_contract():
    """Verify supported relationship types and permitted endpoint label patterns."""
    rel_types = {pattern.rel_type for pattern in RELATIONSHIP_PATTERNS}
    assert rel_types == {
        RelationshipType.CONTAINS,
        RelationshipType.IMPORTS,
        RelationshipType.CALLS,
        RelationshipType.INHERITS,
    }

    # Verify CONTAINS patterns
    contains_patterns = [p for p in RELATIONSHIP_PATTERNS if p.rel_type == RelationshipType.CONTAINS]
    contains_pairs = {
        (src, tgt)
        for p in contains_patterns
        for src in p.source_labels
        for tgt in p.target_labels
    }
    expected_contains = {
        (NodeLabel.REPOSITORY, NodeLabel.FILE),
        (NodeLabel.FILE, NodeLabel.CLASS),
        (NodeLabel.FILE, NodeLabel.FUNCTION),
        (NodeLabel.CLASS, NodeLabel.METHOD),
        (NodeLabel.CLASS, NodeLabel.CLASS),
        (NodeLabel.FUNCTION, NodeLabel.FUNCTION),
    }
    assert contains_pairs == expected_contains

    # Negative assertion: Module and Import MUST NOT have undocumented containment edges
    for src, tgt in contains_pairs:
        assert tgt != NodeLabel.MODULE, "Module must not be the target of a CONTAINS edge"
        assert tgt != NodeLabel.IMPORT, "Import must not be the target of a CONTAINS edge"
        assert src != NodeLabel.MODULE, "Module must not be the source of a CONTAINS edge"
        assert src != NodeLabel.IMPORT, "Import must not be the source of a CONTAINS edge"

    # Verify IMPORTS patterns: File -> Module
    imports_patterns = [p for p in RELATIONSHIP_PATTERNS if p.rel_type == RelationshipType.IMPORTS]
    imports_pairs = {
        (src, tgt)
        for p in imports_patterns
        for src in p.source_labels
        for tgt in p.target_labels
    }
    assert imports_pairs == {(NodeLabel.FILE, NodeLabel.MODULE)}

    # Verify CALLS patterns: Function/Method -> Function/Method
    calls_patterns = [p for p in RELATIONSHIP_PATTERNS if p.rel_type == RelationshipType.CALLS]
    calls_pairs = {
        (src, tgt)
        for p in calls_patterns
        for src in p.source_labels
        for tgt in p.target_labels
    }
    expected_calls = {
        (NodeLabel.FUNCTION, NodeLabel.FUNCTION),
        (NodeLabel.METHOD, NodeLabel.FUNCTION),
        (NodeLabel.METHOD, NodeLabel.METHOD),
        (NodeLabel.FUNCTION, NodeLabel.METHOD),
    }
    assert calls_pairs == expected_calls

    # Verify INHERITS patterns: Class -> Class
    inherits_patterns = [p for p in RELATIONSHIP_PATTERNS if p.rel_type == RelationshipType.INHERITS]
    inherits_pairs = {
        (src, tgt)
        for p in inherits_patterns
        for src in p.source_labels
        for tgt in p.target_labels
    }
    assert inherits_pairs == {(NodeLabel.CLASS, NodeLabel.CLASS)}


def test_uniqueness_constraints_defined_for_all_entity_labels():
    """Verify uniqueness constraints are defined for every entity label on id."""
    constraints = get_schema_constraints()
    assert len(constraints) == 7

    target_labels = {c.label for c in constraints}
    assert target_labels == set(NodeLabel)

    constraint_names = set()
    for c in constraints:
        assert isinstance(c, ConstraintDefinition)
        assert c.property_key == "id"
        assert c.name not in constraint_names, f"Duplicate constraint name: {c.name}"
        constraint_names.add(c.name)

        # Standard Neo4j 5+ idempotent constraint syntax check
        expected_cypher = (
            f"CREATE CONSTRAINT {c.name} IF NOT EXISTS "
            f"FOR (n:{c.label.value}) REQUIRE n.id IS UNIQUE"
        )
        assert c.cypher == expected_cypher


def test_property_indexes_defined_for_repository_scoped_queries():
    """Verify repository-scoped property indexes are defined and non-redundant."""
    indexes = get_schema_indexes()
    assert len(indexes) == 7

    index_names = set()
    for idx in indexes:
        assert isinstance(idx, IndexDefinition)
        assert idx.name not in index_names, f"Duplicate index name: {idx.name}"
        index_names.add(idx.name)

        # Standard Neo4j 5+ idempotent index syntax check
        assert "CREATE INDEX" in idx.cypher
        assert "IF NOT EXISTS" in idx.cypher
        assert f"FOR (n:{idx.label.value})" in idx.cypher

        # Redundancy check: id already has a uniqueness constraint; must NOT have redundant index
        assert "id" not in idx.property_keys, f"Index {idx.name} redundantly indexes 'id'"

    # Check Repository index on name
    repo_indexes = [idx for idx in indexes if idx.label == NodeLabel.REPOSITORY]
    assert len(repo_indexes) == 1
    assert repo_indexes[0].property_keys == ("name",)

    # Check repo_id indexes on other 6 entities
    for lbl in (
        NodeLabel.FILE,
        NodeLabel.MODULE,
        NodeLabel.CLASS,
        NodeLabel.FUNCTION,
        NodeLabel.METHOD,
        NodeLabel.IMPORT,
    ):
        lbl_indexes = [idx for idx in indexes if idx.label == lbl]
        assert len(lbl_indexes) == 1, f"Missing index for {lbl.value}"
        assert lbl_indexes[0].property_keys == ("repo_id",)


def test_schema_cypher_does_not_contain_data_destructive_operations():
    """Verify schema initialization is strictly non-destructive of graph data."""
    statements = get_all_schema_statements()
    assert len(statements) == 14  # 7 constraints + 7 indexes

    forbidden_keywords = ["DELETE", "DETACH", "DROP", "REMOVE", "MATCH", "SET"]
    for stmt in statements:
        uppercase_tokens = stmt.upper().split()
        for forbidden in forbidden_keywords:
            assert forbidden not in uppercase_tokens, (
                f"Destructive or modifying operation '{forbidden}' found in schema Cypher: {stmt}"
            )
        assert stmt.startswith("CREATE CONSTRAINT") or stmt.startswith("CREATE INDEX")


def test_init_schema_with_explicit_session():
    """Verify schema initialization executes all statements in a caller-provided session."""
    mock_session = MagicMock(spec=Session)
    executed = init_schema(session=mock_session)

    assert len(executed) == 14
    assert mock_session.run.call_count == 14

    # Verify each statement was run
    executed_calls = [call.args[0] for call in mock_session.run.call_args_list]
    assert executed_calls == executed

    # Verify session was NOT closed by init_schema when provided externally
    assert not mock_session.close.called


def test_init_schema_with_explicit_driver():
    """Verify schema initialization acquires and closes session via caller-provided driver."""
    mock_session = MagicMock(spec=Session)
    mock_session_cm = MagicMock()
    mock_session_cm.__enter__.return_value = mock_session

    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session_cm

    executed = init_schema(driver=mock_driver)
    assert len(executed) == 14
    mock_driver.session.assert_called_once()
    assert mock_session.run.call_count == 14
    mock_session_cm.__exit__.assert_called_once()


def test_init_schema_with_application_driver():
    """Verify schema initialization uses application-level driver when none is passed."""
    mock_session = MagicMock(spec=Session)
    mock_session_cm = MagicMock()
    mock_session_cm.__enter__.return_value = mock_session

    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.return_value = mock_session_cm
    set_driver(mock_driver)

    executed = init_schema()
    assert len(executed) == 14
    mock_driver.session.assert_called_once()
    assert mock_session.run.call_count == 14


def test_init_schema_uninitialized_driver_raises_schema_error():
    """Verify uninitialized driver raises Neo4jSchemaError without leaking secrets."""
    with pytest.raises(Neo4jSchemaError) as exc_info:
        init_schema()

    assert "Failed to acquire Neo4j driver" in str(exc_info.value)
    # Neo4jSchemaError is a subclass of Neo4jConnectionError
    assert isinstance(exc_info.value, Neo4jConnectionError)


def test_init_schema_idempotency_repeated_runs():
    """Verify repeated execution produces identical statements without error."""
    mock_session = MagicMock(spec=Session)

    first_run = init_schema(session=mock_session)
    second_run = init_schema(session=mock_session)

    assert first_run == second_run
    assert mock_session.run.call_count == 28  # 14 * 2


def test_init_schema_session_failure_raises_schema_error_cleanly():
    """Verify session execution failure raises Neo4jSchemaError and masks internal credentials."""
    mock_session = MagicMock(spec=Session)
    mock_session.run.side_effect = Exception(
        "Connection closed abruptly to bolt://user:super_secret_token@neo4j:7687"
    )

    with pytest.raises(Neo4jSchemaError) as exc_info:
        init_schema(session=mock_session)

    assert "super_secret_token" not in str(exc_info.value)
    assert "Failed to execute schema statements" in str(exc_info.value)
    assert isinstance(exc_info.value, Neo4jConnectionError)


def test_init_schema_driver_session_acquisition_failure():
    """Verify failure during driver session creation raises Neo4jSchemaError cleanly."""
    mock_driver = MagicMock(spec=Driver)
    mock_driver.session.side_effect = Exception("Session pool exhausted for bolt://user:pass@neo4j:7687")

    with pytest.raises(Neo4jSchemaError) as exc_info:
        init_schema(driver=mock_driver)

    assert "pass" not in str(exc_info.value)
    assert "Failed to execute schema statements" in str(exc_info.value)
