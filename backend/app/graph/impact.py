"""Impact analysis engine for Atlas AI (P0-17).

Calculates direct and transitive blast radius of code entities, identifies impacted
entities and affected source files, and enforces repository scoping and depth limits
by reusing the P0-16 graph traversal layer.
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass
import logging
from typing import Any
from neo4j import Driver, Session

from app.db.relationship_persister import repo_id_from_entity_id
from app.graph.traversal import (
    DEFAULT_TRANSITIVE_MAX_DEPTH,
    GraphTraversal,
    GraphTraversalError,
    TraversalNode,
    TraversalResult,
    validate_depth,
)
from app.ucm.identity import build_file_id, normalize_path
from app.ucm.relationships import RelationshipType

logger = logging.getLogger("atlas_ai.impact_engine")


class ImpactAnalysisError(GraphTraversalError):
    """Raised when impact analysis execution fails or database errors occur."""


@dataclass(frozen=True)
class AffectedFile:
    """Represents a source file containing or corresponding to one or more impacted entities.

    Attributes:
        file_id: Deterministic File entity identifier ('{repo_id}::file::{path}').
        path: Normalized repository-relative file path (POSIX style).
    """

    file_id: str
    path: str

    def __str__(self) -> str:
        return self.path

    def __eq__(self, other: object) -> bool:
        if isinstance(other, AffectedFile):
            return self.file_id == other.file_id and self.path == other.path
        if isinstance(other, str):
            return self.file_id == other or self.path == other
        return False

    def __hash__(self) -> int:
        return hash((self.file_id, self.path))


def resolve_affected_files(
    nodes: Iterable[TraversalNode],
    repo_id: str,
) -> tuple[AffectedFile, ...]:
    """Resolve and deduplicate affected source files corresponding to impacted entities.

    Extracts file paths from node properties ('file_path' or 'path') or deserialized
    UCM entity models. If file ownership cannot be established from existing graph data,
    the node is skipped without manufacturing speculative associations.

    Args:
        nodes: Iterable of reached TraversalNode objects.
        repo_id: Scoping repository ID.

    Returns:
        Deduplicated tuple of AffectedFile instances, sorted deterministically by path.
    """
    seen_file_ids: set[str] = set()
    affected: list[AffectedFile] = []

    for node in nodes:
        raw_path: str | None = None

        # 1. Inspect properties
        if "file_path" in node.properties and node.properties["file_path"]:
            raw_path = str(node.properties["file_path"])
        elif "path" in node.properties and node.properties["path"]:
            raw_path = str(node.properties["path"])

        # 2. Inspect entity model if property was missing
        if raw_path is None and node.entity is not None:
            raw_path = getattr(node.entity, "file_path", None) or getattr(node.entity, "path", None)

        if raw_path is None or not str(raw_path).strip():
            # Missing file ownership: safely skip as documented
            continue

        norm_path = normalize_path(raw_path)
        file_id = build_file_id(repo_id, norm_path)

        if file_id not in seen_file_ids:
            seen_file_ids.add(file_id)
            affected.append(AffectedFile(file_id=file_id, path=norm_path))

    # Sort deterministically by relative path
    affected.sort(key=lambda f: f.path)
    return tuple(affected)


@dataclass(frozen=True)
class ImpactAnalysisResult:
    """Encapsulates the complete result of an entity impact analysis.

    Attributes:
        repository_id: Stable identifier of the analyzed repository.
        target_entity_id: Identifier of the target entity whose impact was analyzed.
        max_depth: Maximum traversal depth limit applied.
        directly_impacted_entities: Deduplicated entities at depth 1.
        impacted_entities: All deduplicated impacted entities (depths 1..max_depth).
        affected_files: Deduplicated affected files sorted deterministically.
        target_entity_found: Whether the target entity exists in the repository graph.
    """

    repository_id: str
    target_entity_id: str
    max_depth: int
    directly_impacted_entities: tuple[TraversalNode, ...]
    impacted_entities: tuple[TraversalNode, ...]
    affected_files: tuple[AffectedFile, ...]
    target_entity_found: bool = True

    def __len__(self) -> int:
        return len(self.impacted_entities)

    def __iter__(self):
        return iter(self.impacted_entities)

    def __getitem__(self, index: int) -> TraversalNode:
        return self.impacted_entities[index]

    @property
    def blast_radius(self) -> int:
        """Return the total number of impacted entities."""
        return len(self.impacted_entities)

    @property
    def directly_impacted_count(self) -> int:
        """Return the number of directly impacted entities."""
        return len(self.directly_impacted_entities)

    @property
    def directly_impacted_entity_ids(self) -> list[str]:
        """Return IDs of directly impacted entities in traversal order."""
        return [node.entity_id for node in self.directly_impacted_entities]

    @property
    def impacted_entity_ids(self) -> list[str]:
        """Return IDs of all impacted entities in deterministic traversal order."""
        return [node.entity_id for node in self.impacted_entities]

    @property
    def affected_file_count(self) -> int:
        """Return the number of affected source files."""
        return len(self.affected_files)

    @property
    def affected_file_ids(self) -> list[str]:
        """Return deterministic file IDs of all affected files."""
        return [f.file_id for f in self.affected_files]

    @property
    def affected_file_paths(self) -> list[str]:
        """Return relative paths of all affected files."""
        return [f.path for f in self.affected_files]

    @property
    def by_depth(self) -> dict[int, list[TraversalNode]]:
        """Group all impacted entities by their shortest-path traversal depth."""
        grouped: dict[int, list[TraversalNode]] = {}
        for node in self.impacted_entities:
            grouped.setdefault(node.depth, []).append(node)
        return grouped

    def get_entity(self, entity_id: str) -> TraversalNode | None:
        """Find an impacted entity node by its ID, or return None."""
        for node in self.impacted_entities:
            if node.entity_id == entity_id:
                return node
        return None


class ImpactAnalyzer:
    """Analyzes the blast radius of code changes using graph dependent traversal."""

    def __init__(
        self,
        traversal: GraphTraversal | None = None,
        driver: Driver | None = None,
    ) -> None:
        """Initialize ImpactAnalyzer with an optional GraphTraversal or Driver."""
        self.traversal = traversal if traversal is not None else GraphTraversal(driver=driver)

    def analyze_impact(
        self,
        target_entity_id: str,
        repo_id: str | None = None,
        max_depth: int = DEFAULT_TRANSITIVE_MAX_DEPTH,
        relationship_types: Collection[RelationshipType | str] | None = None,
        session: Session | None = None,
    ) -> ImpactAnalysisResult:
        """Calculate the direct and transitive blast radius of a target entity.

        Reuses the P0-16 reverse dependency traversal to discover all dependent
        entities up to max_depth, separates directly impacted entities (depth 1),
        and maps all impacted entities to unique affected source files.

        Args:
            target_entity_id: Unique deterministic entity ID in Neo4j.
            repo_id: Repository ID scoping analysis. Inferrable from target_entity_id if omitted.
            max_depth: Maximum traversal depth limit (must be an integer >= 1).
            relationship_types: Optional subset of allowed relationships (defaults to CALLS, IMPORTS, INHERITS).
            session: Optional caller-managed Neo4j Session.

        Returns:
            ImpactAnalysisResult with directly impacted entities, transitive impacted entities,
            and affected files.

        Raises:
            ValueError: If target_entity_id or max_depth are invalid.
            ImpactAnalysisError: If Neo4j execution or connection fails.
        """
        if not target_entity_id or not isinstance(target_entity_id, str):
            raise ValueError("target_entity_id must be a non-empty string")

        depth_int = validate_depth(max_depth)

        resolved_repo_id = repo_id
        if resolved_repo_id is None:
            resolved_repo_id = repo_id_from_entity_id(target_entity_id)
            if resolved_repo_id is None:
                raise ValueError("repo_id must be provided or inferrable from target_entity_id")
        elif not isinstance(resolved_repo_id, str) or not resolved_repo_id.strip():
            raise ValueError("repo_id must be a non-empty string when provided")

        try:
            # Execute reverse traversal using P0-16 GraphTraversal API
            traversal_result: TraversalResult = self.traversal.get_dependents(
                entity_id=target_entity_id,
                repo_id=resolved_repo_id,
                max_depth=depth_int,
                relationship_types=relationship_types,
                session=session,
            )
        except GraphTraversalError:
            raise
        except Exception as exc:
            logger.error("Impact analysis failed for entity %s: %s", target_entity_id, type(exc).__name__)
            raise ImpactAnalysisError(f"Impact analysis failed: {type(exc).__name__}") from None

        if not traversal_result.start_entity_found:
            return ImpactAnalysisResult(
                repository_id=resolved_repo_id,
                target_entity_id=target_entity_id,
                max_depth=depth_int,
                directly_impacted_entities=(),
                impacted_entities=(),
                affected_files=(),
                target_entity_found=False,
            )

        impacted_nodes = traversal_result.nodes
        directly_impacted = tuple(n for n in impacted_nodes if n.depth == 1)
        affected_files = resolve_affected_files(impacted_nodes, repo_id=resolved_repo_id)

        return ImpactAnalysisResult(
            repository_id=resolved_repo_id,
            target_entity_id=target_entity_id,
            max_depth=depth_int,
            directly_impacted_entities=directly_impacted,
            impacted_entities=impacted_nodes,
            affected_files=affected_files,
            target_entity_found=True,
        )


def analyze_impact(
    target_entity_id: str,
    repo_id: str | None = None,
    max_depth: int = DEFAULT_TRANSITIVE_MAX_DEPTH,
    relationship_types: Collection[RelationshipType | str] | None = None,
    traversal: GraphTraversal | None = None,
    driver: Driver | None = None,
    session: Session | None = None,
) -> ImpactAnalysisResult:
    """Convenience function to analyze the blast radius of a target code entity."""
    analyzer = ImpactAnalyzer(traversal=traversal, driver=driver)
    return analyzer.analyze_impact(
        target_entity_id=target_entity_id,
        repo_id=repo_id,
        max_depth=max_depth,
        relationship_types=relationship_types,
        session=session,
    )
