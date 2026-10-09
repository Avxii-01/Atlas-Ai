"""Neo4j P0 graph schema definitions, constraints, indexes, and initialization."""

from dataclasses import dataclass
from enum import Enum
import logging
from typing import Any
from neo4j import Driver, Session

from app.db.neo4j import Neo4jConnectionError, get_driver
from app.ucm.relationships import RelationshipType

logger = logging.getLogger("atlas_ai.neo4j_schema")


class Neo4jSchemaError(Neo4jConnectionError):
    """Raised when Neo4j schema definition, constraint, or index initialization fails."""


class NodeLabel(str, Enum):
    """Supported P0 graph schema node labels in Neo4j.

    Conforms to docs/GRAPH_SCHEMA.md and docs/UNIFIED_CODE_MODEL.md.
    """

    REPOSITORY = "Repository"
    FILE = "File"
    MODULE = "Module"
    CLASS = "Class"
    FUNCTION = "Function"
    METHOD = "Method"
    IMPORT = "Import"


@dataclass(frozen=True)
class ConstraintDefinition:
    """Represents a Neo4j uniqueness constraint specification.

    Attributes:
        name: Unique identifier for the constraint.
        label: Target node label.
        property_key: Property on which uniqueness is enforced.
        cypher: Idempotent Cypher statement to create the constraint.
    """

    name: str
    label: NodeLabel
    property_key: str
    cypher: str


@dataclass(frozen=True)
class IndexDefinition:
    """Represents a Neo4j property index specification.

    Attributes:
        name: Unique identifier for the index.
        label: Target node label.
        property_keys: Tuple of property keys indexed.
        cypher: Idempotent Cypher statement to create the index.
    """

    name: str
    label: NodeLabel
    property_keys: tuple[str, ...]
    cypher: str


@dataclass(frozen=True)
class NodePropertySchema:
    """Documented property schema contract for a node label.

    Attributes:
        label: Target node label.
        required_properties: Properties that must always be present.
        optional_properties: Properties that may be null or omitted.
    """

    label: NodeLabel
    required_properties: tuple[str, ...]
    optional_properties: tuple[str, ...] = ()


@dataclass(frozen=True)
class RelationshipPatternSchema:
    """Documented relationship pattern schema contract.

    Attributes:
        rel_type: Type of relationship (CONTAINS, IMPORTS, CALLS, INHERITS).
        source_labels: Valid source node labels.
        target_labels: Valid target node labels.
        required_properties: Properties expected on the relationship edge.
        optional_properties: Optional evidence or metadata properties.
    """

    rel_type: RelationshipType
    source_labels: tuple[NodeLabel, ...]
    target_labels: tuple[NodeLabel, ...]
    required_properties: tuple[str, ...] = ()
    optional_properties: tuple[str, ...] = ()


# Documented Node Property Schemas
NODE_SCHEMAS: dict[NodeLabel, NodePropertySchema] = {
    NodeLabel.REPOSITORY: NodePropertySchema(
        label=NodeLabel.REPOSITORY,
        required_properties=("id", "name", "source"),
        optional_properties=("created_at",),
    ),
    NodeLabel.FILE: NodePropertySchema(
        label=NodeLabel.FILE,
        required_properties=("id", "repo_id", "path", "language", "start_line", "end_line"),
        optional_properties=("start_byte", "end_byte"),
    ),
    NodeLabel.MODULE: NodePropertySchema(
        label=NodeLabel.MODULE,
        required_properties=("id", "repo_id", "name", "qualified_name", "file_path"),
        optional_properties=(),
    ),
    NodeLabel.CLASS: NodePropertySchema(
        label=NodeLabel.CLASS,
        required_properties=(
            "id",
            "repo_id",
            "name",
            "qualified_name",
            "file_path",
            "language",
            "start_line",
            "end_line",
        ),
        optional_properties=("start_byte", "end_byte", "docstring"),
    ),
    NodeLabel.FUNCTION: NodePropertySchema(
        label=NodeLabel.FUNCTION,
        required_properties=(
            "id",
            "repo_id",
            "name",
            "qualified_name",
            "file_path",
            "language",
            "start_line",
            "end_line",
        ),
        optional_properties=("start_byte", "end_byte", "docstring"),
    ),
    NodeLabel.METHOD: NodePropertySchema(
        label=NodeLabel.METHOD,
        required_properties=(
            "id",
            "repo_id",
            "name",
            "qualified_name",
            "file_path",
            "language",
            "start_line",
            "end_line",
        ),
        optional_properties=("start_byte", "end_byte", "docstring"),
    ),
    NodeLabel.IMPORT: NodePropertySchema(
        label=NodeLabel.IMPORT,
        required_properties=(
            "id",
            "repo_id",
            "file_path",
            "module_name",
            "imported_name",
            "start_line",
            "end_line",
        ),
        optional_properties=("alias", "start_byte", "end_byte"),
    ),
}


# Documented Relationship Schemas (CONTAINS, IMPORTS, CALLS, INHERITS)
RELATIONSHIP_PATTERNS: tuple[RelationshipPatternSchema, ...] = (
    # Structural and lexical containment
    RelationshipPatternSchema(
        rel_type=RelationshipType.CONTAINS,
        source_labels=(NodeLabel.REPOSITORY,),
        target_labels=(NodeLabel.FILE,),
    ),
    RelationshipPatternSchema(
        rel_type=RelationshipType.CONTAINS,
        source_labels=(NodeLabel.FILE,),
        target_labels=(NodeLabel.CLASS, NodeLabel.FUNCTION),
    ),
    RelationshipPatternSchema(
        rel_type=RelationshipType.CONTAINS,
        source_labels=(NodeLabel.CLASS,),
        target_labels=(NodeLabel.METHOD, NodeLabel.CLASS),
    ),
    RelationshipPatternSchema(
        rel_type=RelationshipType.CONTAINS,
        source_labels=(NodeLabel.FUNCTION,),
        target_labels=(NodeLabel.FUNCTION,),
    ),
    # Imports
    RelationshipPatternSchema(
        rel_type=RelationshipType.IMPORTS,
        source_labels=(NodeLabel.FILE,),
        target_labels=(NodeLabel.MODULE,),
    ),
    # Calls
    RelationshipPatternSchema(
        rel_type=RelationshipType.CALLS,
        source_labels=(NodeLabel.FUNCTION, NodeLabel.METHOD),
        target_labels=(NodeLabel.FUNCTION, NodeLabel.METHOD),
    ),
    # Inheritance
    RelationshipPatternSchema(
        rel_type=RelationshipType.INHERITS,
        source_labels=(NodeLabel.CLASS,),
        target_labels=(NodeLabel.CLASS,),
    ),
)


# Uniqueness Constraints (Neo4j 5+ standard syntax: REQUIRE n.id IS UNIQUE)
# Each entity type has a deterministic stable ID.
P0_CONSTRAINTS: tuple[ConstraintDefinition, ...] = (
    ConstraintDefinition(
        name="constraint_repository_id",
        label=NodeLabel.REPOSITORY,
        property_key="id",
        cypher="CREATE CONSTRAINT constraint_repository_id IF NOT EXISTS FOR (n:Repository) REQUIRE n.id IS UNIQUE",
    ),
    ConstraintDefinition(
        name="constraint_file_id",
        label=NodeLabel.FILE,
        property_key="id",
        cypher="CREATE CONSTRAINT constraint_file_id IF NOT EXISTS FOR (n:File) REQUIRE n.id IS UNIQUE",
    ),
    ConstraintDefinition(
        name="constraint_module_id",
        label=NodeLabel.MODULE,
        property_key="id",
        cypher="CREATE CONSTRAINT constraint_module_id IF NOT EXISTS FOR (n:Module) REQUIRE n.id IS UNIQUE",
    ),
    ConstraintDefinition(
        name="constraint_class_id",
        label=NodeLabel.CLASS,
        property_key="id",
        cypher="CREATE CONSTRAINT constraint_class_id IF NOT EXISTS FOR (n:Class) REQUIRE n.id IS UNIQUE",
    ),
    ConstraintDefinition(
        name="constraint_function_id",
        label=NodeLabel.FUNCTION,
        property_key="id",
        cypher="CREATE CONSTRAINT constraint_function_id IF NOT EXISTS FOR (n:Function) REQUIRE n.id IS UNIQUE",
    ),
    ConstraintDefinition(
        name="constraint_method_id",
        label=NodeLabel.METHOD,
        property_key="id",
        cypher="CREATE CONSTRAINT constraint_method_id IF NOT EXISTS FOR (n:Method) REQUIRE n.id IS UNIQUE",
    ),
    ConstraintDefinition(
        name="constraint_import_id",
        label=NodeLabel.IMPORT,
        property_key="id",
        cypher="CREATE CONSTRAINT constraint_import_id IF NOT EXISTS FOR (n:Import) REQUIRE n.id IS UNIQUE",
    ),
)


# Property Indexes for Repository-Scoped Queries (Neo4j 5+ standard syntax)
# Enables efficient filtering, traversal, and repository isolation without duplicating unique ID indexes.
P0_INDEXES: tuple[IndexDefinition, ...] = (
    IndexDefinition(
        name="index_repository_name",
        label=NodeLabel.REPOSITORY,
        property_keys=("name",),
        cypher="CREATE INDEX index_repository_name IF NOT EXISTS FOR (n:Repository) ON (n.name)",
    ),
    IndexDefinition(
        name="index_file_repo_id",
        label=NodeLabel.FILE,
        property_keys=("repo_id",),
        cypher="CREATE INDEX index_file_repo_id IF NOT EXISTS FOR (n:File) ON (n.repo_id)",
    ),
    IndexDefinition(
        name="index_module_repo_id",
        label=NodeLabel.MODULE,
        property_keys=("repo_id",),
        cypher="CREATE INDEX index_module_repo_id IF NOT EXISTS FOR (n:Module) ON (n.repo_id)",
    ),
    IndexDefinition(
        name="index_class_repo_id",
        label=NodeLabel.CLASS,
        property_keys=("repo_id",),
        cypher="CREATE INDEX index_class_repo_id IF NOT EXISTS FOR (n:Class) ON (n.repo_id)",
    ),
    IndexDefinition(
        name="index_function_repo_id",
        label=NodeLabel.FUNCTION,
        property_keys=("repo_id",),
        cypher="CREATE INDEX index_function_repo_id IF NOT EXISTS FOR (n:Function) ON (n.repo_id)",
    ),
    IndexDefinition(
        name="index_method_repo_id",
        label=NodeLabel.METHOD,
        property_keys=("repo_id",),
        cypher="CREATE INDEX index_method_repo_id IF NOT EXISTS FOR (n:Method) ON (n.repo_id)",
    ),
    IndexDefinition(
        name="index_import_repo_id",
        label=NodeLabel.IMPORT,
        property_keys=("repo_id",),
        cypher="CREATE INDEX index_import_repo_id IF NOT EXISTS FOR (n:Import) ON (n.repo_id)",
    ),
)


def get_schema_constraints() -> tuple[ConstraintDefinition, ...]:
    """Return all defined P0 uniqueness constraint specifications."""
    return P0_CONSTRAINTS


def get_schema_indexes() -> tuple[IndexDefinition, ...]:
    """Return all defined P0 repository-scoped property index specifications."""
    return P0_INDEXES


def get_constraint_statements() -> list[str]:
    """Return the idempotent Cypher statements for all P0 uniqueness constraints."""
    return [c.cypher for c in P0_CONSTRAINTS]


def get_index_statements() -> list[str]:
    """Return the idempotent Cypher statements for all P0 property indexes."""
    return [idx.cypher for idx in P0_INDEXES]


def get_all_schema_statements() -> list[str]:
    """Return all idempotent Cypher statements (constraints followed by indexes)."""
    return get_constraint_statements() + get_index_statements()


def init_schema(
    driver: Driver | None = None,
    session: Session | None = None,
) -> list[str]:
    """Initialize the Neo4j P0 schema constraints and indexes idempotently.

    Executes standard Neo4j 5+ idempotent DDL statements ('CREATE CONSTRAINT IF NOT EXISTS'
    and 'CREATE INDEX IF NOT EXISTS'). Schema initialization preserves all existing graph
    data and can safely be run repeatedly.

    Args:
        driver: Optional Neo4j Driver instance. If omitted and session is omitted,
            uses the application-level driver from get_driver().
        session: Optional active Neo4j Session. If provided, statements are executed
            within this session without closing it.

    Returns:
        list[str]: The list of executed Cypher statements.

    Raises:
        Neo4jSchemaError: If driver acquisition or statement execution fails.
    """
    statements = get_all_schema_statements()

    if session is not None:
        try:
            for stmt in statements:
                logger.debug("Executing schema Cypher: %s", stmt)
                session.run(stmt)
            logger.info("Successfully executed %d schema statements using provided session", len(statements))
            return statements
        except Exception as exc:
            logger.error("Failed to execute schema statements in provided session: %s", type(exc).__name__)
            raise Neo4jSchemaError(f"Failed to execute schema statements: {type(exc).__name__}") from None

    try:
        target_driver = driver if driver is not None else get_driver()
    except Exception as exc:
        logger.error("Failed to acquire driver for schema initialization: %s", type(exc).__name__)
        raise Neo4jSchemaError(f"Failed to acquire Neo4j driver: {type(exc).__name__}") from None

    try:
        with target_driver.session() as sess:
            for stmt in statements:
                logger.debug("Executing schema Cypher: %s", stmt)
                sess.run(stmt)
        logger.info("Successfully initialized Neo4j schema (%d constraints and indexes)", len(statements))
        return statements
    except Neo4jSchemaError:
        raise
    except Exception as exc:
        logger.error("Failed to execute schema statements: %s", type(exc).__name__)
        raise Neo4jSchemaError(f"Failed to execute schema statements: {type(exc).__name__}") from None
