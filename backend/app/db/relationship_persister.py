"""Neo4j relationship persister for the Unified Code Model (UCM).

Persists resolved relationships into Neo4j using the P0-12 graph schema, enforcing
relationship direction, endpoint existence, repository isolation, and idempotent re-ingestion.
"""

from dataclasses import dataclass
import logging
from typing import Any
from neo4j import Driver, Session

from app.db.entity_persister import Neo4jPersistenceError
from app.db.neo4j import get_driver
from app.db.schema import NodeLabel, RELATIONSHIP_PATTERNS
from app.ucm.model import UnifiedCodeModel
from app.ucm.relationships import Relationship, RelationshipType

logger = logging.getLogger("atlas_ai.neo4j_relationship_persister")


class Neo4jRelationshipPersistenceError(Neo4jPersistenceError):
    """Raised when Neo4j relationship persistence or transaction execution fails."""


@dataclass(frozen=True)
class RelationshipPersistenceResult:
    """Summary of persisted relationships in Neo4j.

    Attributes:
        repository_id: Stable identifier of the analyzed repository.
        persisted_counts: Mapping of relationship type name to count of persisted edges.
        skipped_counts: Mapping of relationship type name to count of skipped edges.
    """

    repository_id: str
    persisted_counts: dict[str, int]
    skipped_counts: dict[str, int]

    @property
    def total_persisted(self) -> int:
        """Return the total number of relationships successfully persisted."""
        return sum(self.persisted_counts.values())

    @property
    def total_skipped(self) -> int:
        """Return the total number of relationships skipped due to missing endpoints or validation."""
        return sum(self.skipped_counts.values())

    def get_persisted_count(self, rel_type: RelationshipType | str) -> int:
        """Return persisted count for a specific relationship type, defaulting to 0."""
        key = rel_type.value if isinstance(rel_type, RelationshipType) else str(rel_type)
        return self.persisted_counts.get(key, 0)

    def get_skipped_count(self, rel_type: RelationshipType | str) -> int:
        """Return skipped count for a specific relationship type, defaulting to 0."""
        key = rel_type.value if isinstance(rel_type, RelationshipType) else str(rel_type)
        return self.skipped_counts.get(key, 0)


ALLOWED_RELATIONSHIP_TRIPLES: set[tuple[str, str, str]] = {
    (pattern.rel_type.value, src.value, tgt.value)
    for pattern in RELATIONSHIP_PATTERNS
    for src in pattern.source_labels
    for tgt in pattern.target_labels
}


def label_from_entity_id(entity_id: str) -> str | None:
    """Derive the expected Neo4j node label from a deterministic UCM entity ID."""
    if not isinstance(entity_id, str):
        return None
    for discriminator, label in (
        ("::file::", "File"),
        ("::module::", "Module"),
        ("::class::", "Class"),
        ("::function::", "Function"),
        ("::method::", "Method"),
        ("::import::", "Import"),
    ):
        if discriminator in entity_id:
            return label
    if entity_id.startswith("repo::"):
        return "Repository"
    return None


def repo_id_from_entity_id(entity_id: str) -> str | None:
    """Extract repository ID prefix from a deterministic UCM entity ID."""
    if not isinstance(entity_id, str):
        return None
    for discriminator in (
        "::file::",
        "::module::",
        "::class::",
        "::function::",
        "::method::",
        "::import::",
    ):
        if discriminator in entity_id:
            return entity_id.split(discriminator)[0]
    if entity_id.startswith("repo::"):
        return entity_id
    return None


def relationship_to_properties(rel: Relationship) -> dict[str, Any]:
    """Convert a UCM relationship's evidence location and metadata into Neo4j edge properties.

    Extracts source location evidence (lines, columns, byte offsets) and scalar metadata,
    omitting null/None values so existing database properties are not erased.
    """
    props: dict[str, Any] = {}
    if rel.location is not None:
        props["start_line"] = rel.location.start_point.line
        props["start_column"] = rel.location.start_point.column
        props["end_line"] = rel.location.end_point.line
        props["end_column"] = rel.location.end_point.column
        props["start_byte"] = rel.location.start_byte
        props["end_byte"] = rel.location.end_byte

    if rel.metadata:
        for k, v in rel.metadata.items():
            if isinstance(v, (str, int, float, bool)):
                props[k] = v
            elif isinstance(v, (list, tuple)) and all(
                isinstance(item, (str, int, float, bool)) for item in v
            ):
                props[k] = list(v)

    return props


def get_relationship_merge_cypher(
    rel_type: str,
    src_label: str,
    tgt_label: str,
) -> str:
    """Return parameterized idempotent Cypher for bulk merging relationships.

    Matches both endpoints using unique constraint index lookups and enforces
    repository isolation. If either endpoint is missing, MATCH produces 0 rows
    and no relationship or missing node is created.
    """
    src_where = (
        "(src:Repository AND src.id = $repo_id) OR src.repo_id = $repo_id"
        if src_label == "Repository"
        else "src.repo_id = $repo_id"
    )
    tgt_where = (
        "(tgt:Repository AND tgt.id = $repo_id) OR tgt.repo_id = $repo_id"
        if tgt_label == "Repository"
        else "tgt.repo_id = $repo_id"
    )

    return (
        f"UNWIND $batch AS rel\n"
        f"MATCH (src:{src_label} {{id: rel.source_id}})\n"
        f"WHERE {src_where}\n"
        f"MATCH (tgt:{tgt_label} {{id: rel.target_id}})\n"
        f"WHERE {tgt_where}\n"
        f"MERGE (src)-[r:{rel_type}]->(tgt)\n"
        f"SET r += rel.properties\n"
        f"RETURN count(r) AS persisted_count"
    )


class RelationshipPersister:
    """Persists Unified Code Model relationships into Neo4j with idempotent write semantics."""

    def __init__(self, driver: Driver | None = None) -> None:
        """Initialize relationship persister with an optional Neo4j driver.

        Args:
            driver: Optional Neo4j Driver instance. If omitted, uses get_driver().
        """
        self.driver = driver

    def persist(
        self,
        ucm: UnifiedCodeModel,
        session: Session | None = None,
    ) -> RelationshipPersistenceResult:
        """Persist all relationships within a UnifiedCodeModel to Neo4j.

        Args:
            ucm: The UnifiedCodeModel containing relationships and entity metadata.
            session: Optional active Neo4j Session. If provided, caller owns the
                session and it will not be closed. If omitted, a session is acquired
                from the driver and safely closed upon completion.

        Returns:
            RelationshipPersistenceResult: Detailed counts of persisted and skipped relationships.

        Raises:
            Neo4jRelationshipPersistenceError: If database persistence or connection fails.
        """
        if not isinstance(ucm, UnifiedCodeModel):
            raise ValueError(f"Expected UnifiedCodeModel, got {type(ucm).__name__}")

        repo_id = ucm.repository.id
        return self._persist_with_lifecycle(
            relationships=ucm.relationships,
            repo_id=repo_id,
            ucm=ucm,
            session=session,
        )

    def persist_relationships(
        self,
        relationships: list[Relationship],
        repo_id: str,
        session: Session | None = None,
    ) -> RelationshipPersistenceResult:
        """Persist a collection of relationships for a specific repository.

        Args:
            relationships: List of Relationship records.
            repo_id: Owning repository ID to enforce isolation.
            session: Optional active Neo4j Session.

        Returns:
            RelationshipPersistenceResult: Detailed counts of persisted and skipped relationships.

        Raises:
            Neo4jRelationshipPersistenceError: If database persistence fails.
        """
        if not repo_id or not isinstance(repo_id, str):
            raise ValueError("repo_id must be a non-empty string")

        return self._persist_with_lifecycle(
            relationships=relationships,
            repo_id=repo_id,
            ucm=None,
            session=session,
        )

    def _persist_with_lifecycle(
        self,
        relationships: list[Relationship],
        repo_id: str,
        ucm: UnifiedCodeModel | None,
        session: Session | None,
    ) -> RelationshipPersistenceResult:
        """Manage session lifecycle and invoke internal persistence routine."""
        if session is not None:
            return self._persist_in_session(relationships, repo_id, ucm, session)

        try:
            target_driver = self.driver if self.driver is not None else get_driver()
        except Exception as exc:
            logger.error("Failed to acquire Neo4j driver: %s", type(exc).__name__)
            raise Neo4jRelationshipPersistenceError("Failed to acquire Neo4j driver.") from None

        try:
            with target_driver.session() as managed_session:
                return self._persist_in_session(relationships, repo_id, ucm, managed_session)
        except Neo4jRelationshipPersistenceError:
            raise
        except Exception as exc:
            logger.error(
                "Failed to persist relationships for repository %s: %s",
                repo_id,
                type(exc).__name__,
            )
            raise Neo4jRelationshipPersistenceError(
                f"Failed to persist relationships: {type(exc).__name__}"
            ) from None

    def _persist_in_session(
        self,
        relationships: list[Relationship],
        repo_id: str,
        ucm: UnifiedCodeModel | None,
        session: Session,
    ) -> RelationshipPersistenceResult:
        """Validate, group, and execute relationship writes inside a session."""
        persisted_counts: dict[str, int] = {
            RelationshipType.CONTAINS.value: 0,
            RelationshipType.IMPORTS.value: 0,
            RelationshipType.CALLS.value: 0,
            RelationshipType.INHERITS.value: 0,
        }
        skipped_counts: dict[str, int] = {
            RelationshipType.CONTAINS.value: 0,
            RelationshipType.IMPORTS.value: 0,
            RelationshipType.CALLS.value: 0,
            RelationshipType.INHERITS.value: 0,
        }

        # Deduplicate relationships by (rel_type, source_id, target_id)
        # Groups: (rel_type, src_label, tgt_label) -> list of batch items
        batches_by_pattern: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

        for rel in relationships:
            rel_type_str = rel.rel_type.value

            # 1. Enforce repository isolation in Python
            src_repo = repo_id_from_entity_id(rel.source_id)
            tgt_repo = repo_id_from_entity_id(rel.target_id)
            if src_repo != repo_id or tgt_repo != repo_id:
                logger.warning(
                    "Skipping cross-repository relationship %s -> %s (expected %s)",
                    rel.source_id,
                    rel.target_id,
                    repo_id,
                )
                skipped_counts[rel_type_str] += 1
                continue

            # 2. Derive and validate endpoint labels
            src_label = label_from_entity_id(rel.source_id)
            tgt_label = label_from_entity_id(rel.target_id)
            if not src_label or not tgt_label:
                logger.warning(
                    "Skipping relationship with unidentifiable endpoint labels: %s -> %s",
                    rel.source_id,
                    rel.target_id,
                )
                skipped_counts[rel_type_str] += 1
                continue

            pattern_triple = (rel_type_str, src_label, tgt_label)
            if pattern_triple not in ALLOWED_RELATIONSHIP_TRIPLES:
                logger.warning(
                    "Skipping undocumented relationship pattern (%s, %s, %s) for %s -> %s",
                    rel_type_str,
                    src_label,
                    tgt_label,
                    rel.source_id,
                    rel.target_id,
                )
                skipped_counts[rel_type_str] += 1
                continue

            # 3. Check endpoint existence in UCM if UCM is available
            if ucm is not None:
                src_entity = ucm.get_entity_by_id(rel.source_id)
                tgt_entity = ucm.get_entity_by_id(rel.target_id)
                if src_entity is None or tgt_entity is None:
                    logger.warning(
                        "Skipping relationship %s -> %s: endpoint not found in UCM",
                        rel.source_id,
                        rel.target_id,
                    )
                    skipped_counts[rel_type_str] += 1
                    continue

            # 4. Prepare batch item
            props = relationship_to_properties(rel)
            batch_item = {
                "source_id": rel.source_id,
                "target_id": rel.target_id,
                "properties": props,
            }

            if pattern_triple not in batches_by_pattern:
                batches_by_pattern[pattern_triple] = []

            # Check if this exact edge already exists in this batch to prevent redundant Cypher calls
            existing_idx = next(
                (
                    i
                    for i, item in enumerate(batches_by_pattern[pattern_triple])
                    if item["source_id"] == rel.source_id and item["target_id"] == rel.target_id
                ),
                None,
            )
            if existing_idx is not None:
                batches_by_pattern[pattern_triple][existing_idx]["properties"].update(props)
            else:
                batches_by_pattern[pattern_triple].append(batch_item)

        try:
            if hasattr(session, "begin_transaction") and callable(session.begin_transaction):
                with session.begin_transaction() as tx:
                    for (rel_type_str, src_lbl, tgt_lbl), batch in batches_by_pattern.items():
                        if not batch:
                            continue
                        cypher = get_relationship_merge_cypher(rel_type_str, src_lbl, tgt_lbl)
                        res = tx.run(cypher, repo_id=repo_id, batch=batch)
                        record = res.single() if hasattr(res, "single") else None
                        persisted = (
                            record["persisted_count"]
                            if record and "persisted_count" in record
                            else len(batch)
                        )
                        persisted_counts[rel_type_str] += persisted
                        diff = len(batch) - persisted
                        if diff > 0:
                            skipped_counts[rel_type_str] += diff
                    tx.commit()
            else:
                for (rel_type_str, src_lbl, tgt_lbl), batch in batches_by_pattern.items():
                    if not batch:
                        continue
                    cypher = get_relationship_merge_cypher(rel_type_str, src_lbl, tgt_lbl)
                    res = session.run(cypher, repo_id=repo_id, batch=batch)
                    record = res.single() if hasattr(res, "single") else None
                    persisted = (
                        record["persisted_count"]
                        if record and "persisted_count" in record
                        else len(batch)
                    )
                    persisted_counts[rel_type_str] += persisted
                    diff = len(batch) - persisted
                    if diff > 0:
                        skipped_counts[rel_type_str] += diff

            logger.info(
                "Persisted %d relationships (%d skipped) for repository %s",
                sum(persisted_counts.values()),
                sum(skipped_counts.values()),
                repo_id,
            )
            return RelationshipPersistenceResult(
                repository_id=repo_id,
                persisted_counts=persisted_counts,
                skipped_counts=skipped_counts,
            )
        except Exception as exc:
            logger.error(
                "Transaction failed while persisting relationships for repository %s: %s",
                repo_id,
                type(exc).__name__,
            )
            raise Neo4jRelationshipPersistenceError(
                f"Failed to persist relationships: {type(exc).__name__}"
            ) from None


def persist_relationships(
    ucm_or_rels: UnifiedCodeModel | list[Relationship],
    repo_id: str | None = None,
    driver: Driver | None = None,
    session: Session | None = None,
) -> RelationshipPersistenceResult:
    """Convenience functional entry point for persisting relationships.

    Args:
        ucm_or_rels: Either a UnifiedCodeModel or a list of Relationship instances.
        repo_id: Repository ID (required if passing a list of relationships).
        driver: Optional Neo4j Driver instance.
        session: Optional active Neo4j Session.

    Returns:
        RelationshipPersistenceResult: Persistence summary.
    """
    persister = RelationshipPersister(driver=driver)
    if isinstance(ucm_or_rels, UnifiedCodeModel):
        return persister.persist(ucm_or_rels, session=session)
    if isinstance(ucm_or_rels, list):
        if not repo_id:
            raise ValueError("repo_id is required when passing a list of relationships")
        return persister.persist_relationships(ucm_or_rels, repo_id=repo_id, session=session)
    raise TypeError(f"Expected UnifiedCodeModel or list[Relationship], got {type(ucm_or_rels).__name__}")
