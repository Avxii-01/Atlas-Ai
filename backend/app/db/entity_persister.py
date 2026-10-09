"""Neo4j entity persister for the Unified Code Model (UCM).

Persists UCM entities into Neo4j using the P0-12 graph schema, enforcing
stable identifiers, repository isolation, and idempotent re-ingestion.
"""

from dataclasses import dataclass
import logging
from typing import Any
from neo4j import Driver, Session

from app.db.neo4j import Neo4jConnectionError, get_driver
from app.db.schema import NodeLabel
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

logger = logging.getLogger("atlas_ai.neo4j_entity_persister")


class Neo4jPersistenceError(Neo4jConnectionError):
    """Raised when Neo4j entity persistence or transaction execution fails."""


@dataclass(frozen=True)
class EntityPersistenceResult:
    """Summary of persisted UCM entities in Neo4j.

    Attributes:
        repository_id: Stable identifier of the analyzed repository.
        persisted_counts: Mapping of node label name to count of persisted entities.
    """

    repository_id: str
    persisted_counts: dict[str, int]

    @property
    def total_entities(self) -> int:
        """Return the total number of entities persisted across all labels."""
        return sum(self.persisted_counts.values())

    def get_count(self, label: NodeLabel | str) -> int:
        """Return the count for a specific label, defaulting to 0."""
        lbl_str = label.value if isinstance(label, NodeLabel) else str(label)
        return self.persisted_counts.get(lbl_str, 0)


ENTITY_PERSISTENCE_ORDER: tuple[NodeLabel, ...] = (
    NodeLabel.REPOSITORY,
    NodeLabel.FILE,
    NodeLabel.MODULE,
    NodeLabel.CLASS,
    NodeLabel.FUNCTION,
    NodeLabel.METHOD,
    NodeLabel.IMPORT,
)


def entity_to_properties(entity: Any) -> dict[str, Any]:
    """Convert a UCM entity into a sanitized property dictionary for Neo4j.

    Excludes keys where the value is None to prevent overwriting existing valid
    properties in the database with empty/null values on re-ingestion.

    Args:
        entity: A UCM entity dataclass instance.

    Returns:
        dict[str, Any]: Property dictionary suitable for Cypher parameterized binding.
    """
    if hasattr(entity, "to_dict"):
        raw_dict = entity.to_dict()
    else:
        raise ValueError(f"Entity of type {type(entity).__name__} does not implement to_dict()")

    return {k: v for k, v in raw_dict.items() if v is not None}


def get_entity_merge_cypher(label: NodeLabel | str) -> str:
    """Return parameterized idempotent Cypher for bulk merging entities of a given label.

    Uses Neo4j's MERGE on entity 'id' backed by uniqueness constraints to ensure
    O(1) lookups and idempotent node creation without duplicates.
    """
    label_val = label.value if isinstance(label, NodeLabel) else str(label)
    return f"UNWIND $batch AS props\nMERGE (n:{label_val} {{id: props.id}})\nSET n += props"


def _prepare_batch(entities: list[Any]) -> list[dict[str, Any]]:
    """Convert a collection of entities to a deduplicated property dictionary batch.

    Deduplicates by entity.id, keeping the latest entity representation.
    """
    deduped: dict[str, dict[str, Any]] = {}
    for entity in entities:
        props = entity_to_properties(entity)
        deduped[props["id"]] = props
    return list(deduped.values())


class EntityPersister:
    """Persists Unified Code Model entities into Neo4j with idempotent write semantics."""

    def __init__(self, driver: Driver | None = None) -> None:
        """Initialize entity persister with an optional Neo4j driver.

        Args:
            driver: Optional Neo4j Driver instance. If omitted, uses get_driver().
        """
        self.driver = driver

    def persist(
        self,
        ucm: UnifiedCodeModel,
        session: Session | None = None,
    ) -> EntityPersistenceResult:
        """Persist all entities within a UnifiedCodeModel to Neo4j.

        Args:
            ucm: The UnifiedCodeModel containing entities to persist.
            session: Optional active Neo4j Session. If provided, the caller owns the
                session and it will not be closed. If omitted, a session is acquired
                from the driver and safely closed after completion.

        Returns:
            EntityPersistenceResult: Detailed counts of persisted entities.

        Raises:
            Neo4jPersistenceError: If database persistence fails or connection is unavailable.
        """
        if not isinstance(ucm, UnifiedCodeModel):
            raise ValueError(f"Expected UnifiedCodeModel, got {type(ucm).__name__}")

        if session is not None:
            return self._persist_in_session(ucm, session)

        try:
            target_driver = self.driver if self.driver is not None else get_driver()
        except Exception as exc:
            logger.error("Failed to acquire Neo4j driver: %s", type(exc).__name__)
            raise Neo4jPersistenceError("Failed to acquire Neo4j driver.") from None

        try:
            with target_driver.session() as managed_session:
                return self._persist_in_session(ucm, managed_session)
        except Neo4jPersistenceError:
            raise
        except Exception as exc:
            logger.error(
                "Failed to persist entities for repository %s: %s",
                ucm.repository.id,
                type(exc).__name__,
            )
            raise Neo4jPersistenceError(
                f"Failed to persist entities: {type(exc).__name__}"
            ) from None

    def _persist_in_session(
        self,
        ucm: UnifiedCodeModel,
        session: Session,
    ) -> EntityPersistenceResult:
        """Execute entity persistence inside a given session with transaction boundaries."""
        batches: dict[NodeLabel, list[dict[str, Any]]] = {
            NodeLabel.REPOSITORY: [entity_to_properties(ucm.repository)],
            NodeLabel.FILE: _prepare_batch(ucm.files),
            NodeLabel.MODULE: _prepare_batch(ucm.modules),
            NodeLabel.CLASS: _prepare_batch(ucm.classes),
            NodeLabel.FUNCTION: _prepare_batch(ucm.functions),
            NodeLabel.METHOD: _prepare_batch(ucm.methods),
            NodeLabel.IMPORT: _prepare_batch(ucm.imports),
        }

        persisted_counts: dict[str, int] = {}

        try:
            if hasattr(session, "begin_transaction") and callable(session.begin_transaction):
                with session.begin_transaction() as tx:
                    for label in ENTITY_PERSISTENCE_ORDER:
                        batch = batches.get(label, [])
                        if batch:
                            cypher = get_entity_merge_cypher(label)
                            logger.debug("Persisting %d %s entities", len(batch), label.value)
                            tx.run(cypher, batch=batch)
                        persisted_counts[label.value] = len(batch)
                    tx.commit()
            else:
                for label in ENTITY_PERSISTENCE_ORDER:
                    batch = batches.get(label, [])
                    if batch:
                        cypher = get_entity_merge_cypher(label)
                        logger.debug("Persisting %d %s entities", len(batch), label.value)
                        session.run(cypher, batch=batch)
                    persisted_counts[label.value] = len(batch)

            logger.info(
                "Successfully persisted %d entities for repository %s",
                sum(persisted_counts.values()),
                ucm.repository.id,
            )
            return EntityPersistenceResult(
                repository_id=ucm.repository.id,
                persisted_counts=persisted_counts,
            )
        except Exception as exc:
            logger.error(
                "Transaction failed while persisting entities for repository %s: %s",
                ucm.repository.id,
                type(exc).__name__,
            )
            raise Neo4jPersistenceError(
                f"Failed to persist entities: {type(exc).__name__}"
            ) from None

    def persist_entity_batch(
        self,
        label: NodeLabel | str,
        entities: list[Any],
        session: Session | None = None,
    ) -> int:
        """Persist a single batch of entities of a specific label.

        Args:
            label: The NodeLabel representing the entity type.
            entities: Collection of UCM entities.
            session: Optional active Session. If omitted, acquires a managed session.

        Returns:
            int: Number of entities persisted.
        """
        batch = _prepare_batch(entities)
        if not batch:
            return 0

        cypher = get_entity_merge_cypher(label)

        if session is not None:
            session.run(cypher, batch=batch)
            return len(batch)

        try:
            target_driver = self.driver if self.driver is not None else get_driver()
            with target_driver.session() as managed_sess:
                managed_sess.run(cypher, batch=batch)
            return len(batch)
        except Exception as exc:
            logger.error("Failed to persist %s batch: %s", label, type(exc).__name__)
            raise Neo4jPersistenceError(f"Failed to persist {label} batch.") from None

    def persist_repository(self, repository: Repository, session: Session | None = None) -> int:
        """Persist a single Repository entity."""
        return self.persist_entity_batch(NodeLabel.REPOSITORY, [repository], session=session)

    def persist_files(self, files: list[File], session: Session | None = None) -> int:
        """Persist a collection of File entities."""
        return self.persist_entity_batch(NodeLabel.FILE, files, session=session)

    def persist_modules(self, modules: list[Module], session: Session | None = None) -> int:
        """Persist a collection of Module entities."""
        return self.persist_entity_batch(NodeLabel.MODULE, modules, session=session)

    def persist_classes(self, classes: list[Class], session: Session | None = None) -> int:
        """Persist a collection of Class entities."""
        return self.persist_entity_batch(NodeLabel.CLASS, classes, session=session)

    def persist_functions(self, functions: list[Function], session: Session | None = None) -> int:
        """Persist a collection of Function entities."""
        return self.persist_entity_batch(NodeLabel.FUNCTION, functions, session=session)

    def persist_methods(self, methods: list[Method], session: Session | None = None) -> int:
        """Persist a collection of Method entities."""
        return self.persist_entity_batch(NodeLabel.METHOD, methods, session=session)

    def persist_imports(self, imports: list[Import], session: Session | None = None) -> int:
        """Persist a collection of Import entities."""
        return self.persist_entity_batch(NodeLabel.IMPORT, imports, session=session)


def persist_entities(
    ucm: UnifiedCodeModel,
    driver: Driver | None = None,
    session: Session | None = None,
) -> EntityPersistenceResult:
    """Convenience functional entry point for persisting all entities within a UCM.

    Args:
        ucm: UnifiedCodeModel instance.
        driver: Optional Neo4j Driver instance.
        session: Optional active Neo4j Session.

    Returns:
        EntityPersistenceResult: Persistence summary.
    """
    persister = EntityPersister(driver=driver)
    return persister.persist(ucm, session=session)
