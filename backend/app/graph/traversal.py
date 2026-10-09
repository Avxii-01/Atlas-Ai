"""Repository-scoped Neo4j graph traversal for Atlas AI.

Retrieves direct and transitive dependencies and dependents from the persisted Neo4j code graph
using bounded, cycle-safe Cypher queries with strict repository isolation.
"""

from collections.abc import Collection
from dataclasses import dataclass
from enum import Enum
import logging
from typing import Any
from neo4j import Driver, Session

from app.db.graph_retriever import ENTITY_FACTORIES, record_to_entity
from app.db.neo4j import Neo4jConnectionError, get_driver
from app.db.relationship_persister import label_from_entity_id, repo_id_from_entity_id
from app.ucm.relationships import RelationshipType

logger = logging.getLogger("atlas_ai.graph_traversal")


class GraphTraversalError(Neo4jConnectionError):
    """Raised when Neo4j graph traversal fails or database error occurs."""


class TraversalDirection(str, Enum):
    """Traversal direction relative to the start entity."""

    DEPENDENCIES = "dependencies"
    DEPENDENTS = "dependents"


DEFAULT_DEPENDENCY_RELATIONSHIPS: tuple[str, ...] = (
    RelationshipType.CALLS.value,
    RelationshipType.IMPORTS.value,
    RelationshipType.INHERITS.value,
)

ALL_ALLOWED_RELATIONSHIPS: frozenset[str] = frozenset(
    {
        RelationshipType.CONTAINS.value,
        RelationshipType.IMPORTS.value,
        RelationshipType.CALLS.value,
        RelationshipType.INHERITS.value,
    }
)

DEFAULT_TRANSITIVE_MAX_DEPTH: int = 10


def validate_relationship_types(
    rel_types: Collection[RelationshipType | str] | None,
) -> tuple[str, ...]:
    """Validate and normalize requested relationship types against internal allowlist.

    By default (when rel_types is None), returns the dependency types (CALLS, IMPORTS, INHERITS).
    Structural CONTAINS is excluded by default.

    Args:
        rel_types: Optional collection of RelationshipType enums or string names.

    Returns:
        Sorted tuple of validated uppercase relationship type strings.

    Raises:
        ValueError: If rel_types is empty or contains an unsupported relationship type.
    """
    if rel_types is None:
        return DEFAULT_DEPENDENCY_RELATIONSHIPS

    if not rel_types:
        raise ValueError("relationship_types must not be empty if specified")

    validated: list[str] = []
    for t in rel_types:
        if not t or not isinstance(t, (str, RelationshipType)):
            raise ValueError(f"Invalid relationship type item: {t!r}")
        name = t.value if isinstance(t, RelationshipType) else str(t).strip().upper()
        if name not in ALL_ALLOWED_RELATIONSHIPS:
            raise ValueError(
                f"Unsupported relationship type '{t}'. "
                f"Allowed types: {sorted(ALL_ALLOWED_RELATIONSHIPS)}"
            )
        validated.append(name)

    return tuple(sorted(set(validated)))


def validate_depth(depth: int) -> int:
    """Validate traversal depth parameter.

    Args:
        depth: Traversal depth limit (must be an integer >= 1).

    Returns:
        The validated depth integer.

    Raises:
        ValueError: If depth is not an integer or is less than 1.
    """
    if not isinstance(depth, int) or isinstance(depth, bool) or depth < 1:
        raise ValueError(f"Traversal depth must be an integer >= 1, got {depth!r}")
    return depth


@dataclass(frozen=True)
class TraversalNode:
    """Represents an entity reached during graph traversal.

    Attributes:
        entity_id: Deterministic identifier of the reached entity.
        depth: Shortest path distance (hop count) from the start entity.
        labels: Tuple of Neo4j node labels (e.g. ('Function',), ('Class',)).
        properties: Raw properties retrieved from Neo4j.
        path_relationship_types: Sequence of relationship types traversed on the shortest path.
        entity: Deserialized typed UCM entity model if reconstructable, else None.
    """

    entity_id: str
    depth: int
    labels: tuple[str, ...]
    properties: dict[str, Any]
    path_relationship_types: tuple[str, ...] = ()
    entity: Any | None = None

    @property
    def primary_label(self) -> str | None:
        """Return the primary entity label if available."""
        if self.labels:
            return self.labels[0]
        return None


@dataclass(frozen=True)
class TraversalResult:
    """Result of a repository-scoped graph traversal.

    Attributes:
        start_entity_id: The entity ID where traversal started.
        repository_id: The repository ID to which traversal was scoped.
        direction: Direction traversed ('dependencies' or 'dependents').
        max_depth: Maximum traversal depth limit applied.
        relationship_types: Tuple of relationship types included in traversal.
        nodes: Deterministically ordered tuple of reached TraversalNode objects.
        start_entity_found: Whether the starting entity exists in the repository graph.
    """

    start_entity_id: str
    repository_id: str
    direction: TraversalDirection
    max_depth: int
    relationship_types: tuple[str, ...]
    nodes: tuple[TraversalNode, ...]
    start_entity_found: bool = True

    def __len__(self) -> int:
        return len(self.nodes)

    def __iter__(self):
        return iter(self.nodes)

    def __getitem__(self, index: int) -> TraversalNode:
        return self.nodes[index]

    @property
    def entity_ids(self) -> list[str]:
        """Return reached entity IDs in deterministic traversal order."""
        return [node.entity_id for node in self.nodes]

    @property
    def by_depth(self) -> dict[int, list[TraversalNode]]:
        """Group reached nodes by traversal depth."""
        grouped: dict[int, list[TraversalNode]] = {}
        for node in self.nodes:
            grouped.setdefault(node.depth, []).append(node)
        return grouped

    def get_node(self, entity_id: str) -> TraversalNode | None:
        """Find a reached node by its entity ID, or return None."""
        for node in self.nodes:
            if node.entity_id == entity_id:
                return node
        return None


def build_traversal_cypher(
    direction: TraversalDirection,
    max_depth: int,
    relationship_types: tuple[str, ...],
    start_label: str | None = None,
) -> str:
    """Construct parameterized Cypher query for bounded graph traversal.

    Strictly read-only MATCH ... RETURN query. Enforces repository isolation on
    start node, target node, and all intermediate path nodes. Deduplicates targets
    by shortest path distance and sorts deterministically.

    Args:
        direction: DEPENDENCIES (outgoing) or DEPENDENTS (incoming).
        max_depth: Validated maximum path depth limit.
        relationship_types: Validated tuple of relationship type names.
        start_label: Optional verified node label for start node lookup optimization.

    Returns:
        Parameterized Cypher query string.
    """
    rel_pattern = "|".join(relationship_types)
    pattern_hop = f":{rel_pattern}*1..{max_depth}"

    start_clause = f"(start:{start_label} {{id: $entity_id}})" if start_label else "(start {id: $entity_id})"

    if start_label == "Repository":
        start_repo_filter = "start.id = $repo_id"
    elif start_label is not None:
        start_repo_filter = "start.repo_id = $repo_id"
    else:
        start_repo_filter = "((start:Repository AND start.id = $repo_id) OR start.repo_id = $repo_id)"

    if direction == TraversalDirection.DEPENDENCIES:
        path_pattern = f"(start)-[{pattern_hop}]->(target)"
    else:
        path_pattern = f"(start)<-[{pattern_hop}]-(target)"

    return (
        f"MATCH {start_clause}\n"
        f"WHERE {start_repo_filter}\n"
        f"OPTIONAL MATCH path = {path_pattern}\n"
        f"WHERE ((target:Repository AND target.id = $repo_id) OR target.repo_id = $repo_id)\n"
        f"  AND ALL(node IN nodes(path) WHERE (node:Repository AND node.id = $repo_id) OR node.repo_id = $repo_id)\n"
        f"  AND target.id <> $entity_id\n"
        f"WITH start, target, path\n"
        f"ORDER BY length(path) ASC\n"
        f"WITH start, target, head(collect(path)) AS shortest_path\n"
        f"RETURN target.id AS entity_id,\n"
        f"       labels(target) AS labels,\n"
        f"       properties(target) AS properties,\n"
        f"       length(shortest_path) AS depth,\n"
        f"       CASE WHEN shortest_path IS NULL THEN [] ELSE [rel IN relationships(shortest_path) | type(rel)] END AS rel_types,\n"
        f"       start.id AS start_id\n"
        f"ORDER BY depth ASC, entity_id ASC"
    )


class GraphTraversal:
    """Executes bounded, cycle-safe graph traversals on the Neo4j code graph."""

    def __init__(self, driver: Driver | None = None) -> None:
        """Initialize GraphTraversal with an optional Neo4j Driver."""
        self.driver = driver

    def _get_session(self, session: Session | None) -> tuple[Session, bool]:
        """Acquire a session and return (session, is_managed)."""
        if session is not None:
            return session, False
        try:
            target_driver = self.driver if self.driver is not None else get_driver()
            return target_driver.session(), True
        except Exception as exc:
            logger.error("Failed to acquire Neo4j driver: %s", type(exc).__name__)
            raise GraphTraversalError("Failed to acquire Neo4j driver.") from None

    def _traverse(
        self,
        entity_id: str,
        direction: TraversalDirection,
        repo_id: str | None = None,
        max_depth: int = 1,
        relationship_types: Collection[RelationshipType | str] | None = None,
        session: Session | None = None,
    ) -> TraversalResult:
        """Internal worker executing bounded graph traversal."""
        if not entity_id or not isinstance(entity_id, str):
            raise ValueError("entity_id must be a non-empty string")

        depth_int = validate_depth(max_depth)
        validated_rel_types = validate_relationship_types(relationship_types)

        # Resolve and validate repository scoping
        resolved_repo_id = repo_id
        if resolved_repo_id is None:
            resolved_repo_id = repo_id_from_entity_id(entity_id)
            if resolved_repo_id is None:
                raise ValueError("repo_id must be provided or inferrable from entity_id")
        elif not isinstance(resolved_repo_id, str) or not resolved_repo_id.strip():
            raise ValueError("repo_id must be a non-empty string when provided")

        start_label = label_from_entity_id(entity_id)
        cypher = build_traversal_cypher(
            direction=direction,
            max_depth=depth_int,
            relationship_types=validated_rel_types,
            start_label=start_label,
        )

        sess, is_managed = self._get_session(session)
        try:
            records = list(
                sess.run(
                    cypher,
                    entity_id=entity_id,
                    repo_id=resolved_repo_id,
                )
            )

            if not records:
                # Start entity not found or repository mismatch
                return TraversalResult(
                    start_entity_id=entity_id,
                    repository_id=resolved_repo_id,
                    direction=direction,
                    max_depth=depth_int,
                    relationship_types=validated_rel_types,
                    nodes=(),
                    start_entity_found=False,
                )

            start_found = any(r.get("start_id") is not None for r in records)
            nodes: list[TraversalNode] = []

            for record in records:
                target_id = record.get("entity_id")
                if target_id is None:
                    # Empty neighborhood for start entity
                    continue

                raw_labels = record.get("labels") or []
                labels_tuple = tuple(raw_labels)
                properties = dict(record.get("properties") or {})
                depth = int(record["depth"])
                rel_types_raw = record.get("rel_types") or []
                rel_types_tuple = tuple(rel_types_raw)

                # Reconstruct typed UCM entity model if possible
                entity_obj = None
                primary_label = next((lbl for lbl in raw_labels if lbl in ENTITY_FACTORIES), None)
                if primary_label:
                    try:
                        entity_obj = record_to_entity(primary_label, properties)
                    except Exception:
                        entity_obj = None

                nodes.append(
                    TraversalNode(
                        entity_id=target_id,
                        depth=depth,
                        labels=labels_tuple,
                        properties=properties,
                        path_relationship_types=rel_types_tuple,
                        entity=entity_obj,
                    )
                )

            return TraversalResult(
                start_entity_id=entity_id,
                repository_id=resolved_repo_id,
                direction=direction,
                max_depth=depth_int,
                relationship_types=validated_rel_types,
                nodes=tuple(nodes),
                start_entity_found=start_found,
            )
        except GraphTraversalError:
            raise
        except Exception as exc:
            logger.error("Failed to traverse graph for entity %s: %s", entity_id, type(exc).__name__)
            raise GraphTraversalError(f"Failed to traverse graph: {type(exc).__name__}") from None
        finally:
            if is_managed:
                sess.close()

    def get_dependencies(
        self,
        entity_id: str,
        repo_id: str | None = None,
        max_depth: int = 1,
        relationship_types: Collection[RelationshipType | str] | None = None,
        session: Session | None = None,
    ) -> TraversalResult:
        """Traverse outgoing dependencies from entity_id up to max_depth.

        Semantics: A -> B -> C
        - Depth 1 returns B.
        - Depth 2 returns B and C.

        Args:
            entity_id: Unique deterministic entity ID in Neo4j.
            repo_id: Repository ID to scope traversal. Inferrable from entity_id if omitted.
            max_depth: Maximum hops (>= 1, default 1 for direct dependencies).
            relationship_types: Optional subset of allowed relationships.
                Defaults to ('CALLS', 'IMPORTS', 'INHERITS').
            session: Optional caller-managed Neo4j Session.

        Returns:
            TraversalResult containing deduplicated reached nodes ordered by depth and ID.
        """
        return self._traverse(
            entity_id=entity_id,
            direction=TraversalDirection.DEPENDENCIES,
            repo_id=repo_id,
            max_depth=max_depth,
            relationship_types=relationship_types,
            session=session,
        )

    def get_direct_dependencies(
        self,
        entity_id: str,
        repo_id: str | None = None,
        relationship_types: Collection[RelationshipType | str] | None = None,
        session: Session | None = None,
    ) -> TraversalResult:
        """Traverse direct (depth 1) outgoing dependencies from entity_id."""
        return self.get_dependencies(
            entity_id=entity_id,
            repo_id=repo_id,
            max_depth=1,
            relationship_types=relationship_types,
            session=session,
        )

    def get_transitive_dependencies(
        self,
        entity_id: str,
        repo_id: str | None = None,
        max_depth: int = DEFAULT_TRANSITIVE_MAX_DEPTH,
        relationship_types: Collection[RelationshipType | str] | None = None,
        session: Session | None = None,
    ) -> TraversalResult:
        """Traverse transitive outgoing dependencies from entity_id up to max_depth."""
        return self.get_dependencies(
            entity_id=entity_id,
            repo_id=repo_id,
            max_depth=max_depth,
            relationship_types=relationship_types,
            session=session,
        )

    def get_dependents(
        self,
        entity_id: str,
        repo_id: str | None = None,
        max_depth: int = 1,
        relationship_types: Collection[RelationshipType | str] | None = None,
        session: Session | None = None,
    ) -> TraversalResult:
        """Traverse incoming dependents (reverse dependencies) of entity_id up to max_depth.

        Semantics: A -> B -> C
        - Direct dependents of C at depth 1: B.
        - Transitive dependents of C at depth 2: B and A.

        Args:
            entity_id: Unique deterministic entity ID in Neo4j.
            repo_id: Repository ID to scope traversal. Inferrable from entity_id if omitted.
            max_depth: Maximum hops (>= 1, default 1 for direct dependents).
            relationship_types: Optional subset of allowed relationships.
                Defaults to ('CALLS', 'IMPORTS', 'INHERITS').
            session: Optional caller-managed Neo4j Session.

        Returns:
            TraversalResult containing deduplicated reached nodes ordered by depth and ID.
        """
        return self._traverse(
            entity_id=entity_id,
            direction=TraversalDirection.DEPENDENTS,
            repo_id=repo_id,
            max_depth=max_depth,
            relationship_types=relationship_types,
            session=session,
        )

    def get_direct_dependents(
        self,
        entity_id: str,
        repo_id: str | None = None,
        relationship_types: Collection[RelationshipType | str] | None = None,
        session: Session | None = None,
    ) -> TraversalResult:
        """Traverse direct (depth 1) incoming dependents of entity_id."""
        return self.get_dependents(
            entity_id=entity_id,
            repo_id=repo_id,
            max_depth=1,
            relationship_types=relationship_types,
            session=session,
        )

    def get_transitive_dependents(
        self,
        entity_id: str,
        repo_id: str | None = None,
        max_depth: int = DEFAULT_TRANSITIVE_MAX_DEPTH,
        relationship_types: Collection[RelationshipType | str] | None = None,
        session: Session | None = None,
    ) -> TraversalResult:
        """Traverse transitive incoming dependents of entity_id up to max_depth."""
        return self.get_dependents(
            entity_id=entity_id,
            repo_id=repo_id,
            max_depth=max_depth,
            relationship_types=relationship_types,
            session=session,
        )


# Functional convenience entry points


def get_dependencies(
    entity_id: str,
    repo_id: str | None = None,
    max_depth: int = 1,
    relationship_types: Collection[RelationshipType | str] | None = None,
    driver: Driver | None = None,
    session: Session | None = None,
) -> TraversalResult:
    """Convenience function to traverse outgoing dependencies."""
    traversal = GraphTraversal(driver=driver)
    return traversal.get_dependencies(
        entity_id=entity_id,
        repo_id=repo_id,
        max_depth=max_depth,
        relationship_types=relationship_types,
        session=session,
    )


def get_direct_dependencies(
    entity_id: str,
    repo_id: str | None = None,
    relationship_types: Collection[RelationshipType | str] | None = None,
    driver: Driver | None = None,
    session: Session | None = None,
) -> TraversalResult:
    """Convenience function to traverse direct outgoing dependencies."""
    traversal = GraphTraversal(driver=driver)
    return traversal.get_direct_dependencies(
        entity_id=entity_id,
        repo_id=repo_id,
        relationship_types=relationship_types,
        session=session,
    )


def get_transitive_dependencies(
    entity_id: str,
    repo_id: str | None = None,
    max_depth: int = DEFAULT_TRANSITIVE_MAX_DEPTH,
    relationship_types: Collection[RelationshipType | str] | None = None,
    driver: Driver | None = None,
    session: Session | None = None,
) -> TraversalResult:
    """Convenience function to traverse transitive outgoing dependencies."""
    traversal = GraphTraversal(driver=driver)
    return traversal.get_transitive_dependencies(
        entity_id=entity_id,
        repo_id=repo_id,
        max_depth=max_depth,
        relationship_types=relationship_types,
        session=session,
    )


def get_dependents(
    entity_id: str,
    repo_id: str | None = None,
    max_depth: int = 1,
    relationship_types: Collection[RelationshipType | str] | None = None,
    driver: Driver | None = None,
    session: Session | None = None,
) -> TraversalResult:
    """Convenience function to traverse incoming dependents."""
    traversal = GraphTraversal(driver=driver)
    return traversal.get_dependents(
        entity_id=entity_id,
        repo_id=repo_id,
        max_depth=max_depth,
        relationship_types=relationship_types,
        session=session,
    )


def get_direct_dependents(
    entity_id: str,
    repo_id: str | None = None,
    relationship_types: Collection[RelationshipType | str] | None = None,
    driver: Driver | None = None,
    session: Session | None = None,
) -> TraversalResult:
    """Convenience function to traverse direct incoming dependents."""
    traversal = GraphTraversal(driver=driver)
    return traversal.get_direct_dependents(
        entity_id=entity_id,
        repo_id=repo_id,
        relationship_types=relationship_types,
        session=session,
    )


def get_transitive_dependents(
    entity_id: str,
    repo_id: str | None = None,
    max_depth: int = DEFAULT_TRANSITIVE_MAX_DEPTH,
    relationship_types: Collection[RelationshipType | str] | None = None,
    driver: Driver | None = None,
    session: Session | None = None,
) -> TraversalResult:
    """Convenience function to traverse transitive incoming dependents."""
    traversal = GraphTraversal(driver=driver)
    return traversal.get_transitive_dependents(
        entity_id=entity_id,
        repo_id=repo_id,
        max_depth=max_depth,
        relationship_types=relationship_types,
        session=session,
    )
