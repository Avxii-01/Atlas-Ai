"""Neo4j graph retrieval layer for the Unified Code Model (UCM).

Queries persisted Atlas AI code entities and relationships from Neo4j and converts
them into typed Unified Code Model entities and relationships for downstream analysis.
"""

import logging
from typing import Any
from neo4j import Driver, Session

from app.db.neo4j import Neo4jConnectionError, get_driver
from app.db.relationship_persister import label_from_entity_id
from app.db.schema import NodeLabel
from app.parser.models import SourcePosition, SourceRange
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
from app.ucm.relationships import Relationship, RelationshipType

logger = logging.getLogger("atlas_ai.neo4j_graph_retriever")


class Neo4jRetrievalError(Neo4jConnectionError):
    """Raised when Neo4j graph entity or relationship retrieval fails."""


ENTITY_FACTORIES: dict[str, type] = {
    NodeLabel.REPOSITORY.value: Repository,
    NodeLabel.FILE.value: File,
    NodeLabel.MODULE.value: Module,
    NodeLabel.CLASS.value: Class,
    NodeLabel.FUNCTION.value: Function,
    NodeLabel.METHOD.value: Method,
    NodeLabel.IMPORT.value: Import,
}

LOCATION_PROPERTY_KEYS: frozenset[str] = frozenset(
    {
        "start_line",
        "start_column",
        "end_line",
        "end_column",
        "start_byte",
        "end_byte",
    }
)


def record_to_entity(label: str, props: dict[str, Any]) -> Any:
    """Convert a Neo4j property dictionary into a typed UCM entity model.

    Args:
        label: Node label name (e.g. 'File', 'Class', 'Repository').
        props: Dictionary of node properties from Neo4j.

    Returns:
        UCM entity instance (Repository, File, Module, Class, Function, Method, Import).

    Raises:
        ValueError: If label is unknown or unrecognized.
    """
    factory = ENTITY_FACTORIES.get(label)
    if factory is None:
        raise ValueError(f"Unknown entity label: {label}")

    clean_props = dict(props)
    if label in (NodeLabel.FILE.value, NodeLabel.IMPORT.value):
        clean_props.setdefault("start_byte", 0)
        clean_props.setdefault("end_byte", 0)

    return factory.from_dict(clean_props)


def record_to_relationship(
    source_id: str,
    target_id: str,
    rel_type: str,
    properties: dict[str, Any],
) -> Relationship:
    """Convert Neo4j relationship query results into a typed UCM Relationship model.

    Extracts location evidence (lines, columns, byte offsets) into a SourceRange,
    and moves remaining properties into metadata.
    """
    location = None
    if "start_line" in properties and "end_line" in properties:
        location = SourceRange(
            start_point=SourcePosition(
                line=int(properties["start_line"]),
                column=int(properties.get("start_column", 0)),
            ),
            end_point=SourcePosition(
                line=int(properties["end_line"]),
                column=int(properties.get("end_column", 0)),
            ),
            start_byte=int(properties.get("start_byte", 0)),
            end_byte=int(properties.get("end_byte", 0)),
        )

    metadata = {k: v for k, v in properties.items() if k not in LOCATION_PROPERTY_KEYS}

    return Relationship(
        rel_type=RelationshipType(rel_type),
        source_id=source_id,
        target_id=target_id,
        location=location,
        metadata=metadata,
    )


class GraphRetriever:
    """Retrieves persisted code entities and relationships from Neo4j into UCM models."""

    def __init__(self, driver: Driver | None = None) -> None:
        """Initialize GraphRetriever with an optional Neo4j Driver."""
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
            raise Neo4jRetrievalError("Failed to acquire Neo4j driver.") from None

    def get_repository(self, repo_id: str, session: Session | None = None) -> Repository | None:
        """Retrieve a Repository entity by its unique ID. Returns None if not found."""
        if not repo_id or not isinstance(repo_id, str):
            raise ValueError("repo_id must be a non-empty string")

        sess, is_managed = self._get_session(session)
        try:
            cypher = "MATCH (r:Repository {id: $repo_id})\nRETURN properties(r) AS props"
            res = sess.run(cypher, repo_id=repo_id).single()
            if res and "props" in res:
                return record_to_entity(NodeLabel.REPOSITORY.value, res["props"])
            return None
        except Neo4jRetrievalError:
            raise
        except Exception as exc:
            logger.error("Failed to retrieve repository %s: %s", repo_id, type(exc).__name__)
            raise Neo4jRetrievalError(f"Failed to retrieve repository: {type(exc).__name__}") from None
        finally:
            if is_managed:
                sess.close()

    def get_entity_by_id(
        self,
        entity_id: str,
        repo_id: str | None = None,
        session: Session | None = None,
    ) -> Any | None:
        """Retrieve a single entity by its deterministic ID. Returns None if not found."""
        if not entity_id or not isinstance(entity_id, str):
            raise ValueError("entity_id must be a non-empty string")

        expected_label = label_from_entity_id(entity_id)
        sess, is_managed = self._get_session(session)
        try:
            if expected_label == NodeLabel.REPOSITORY.value:
                return self.get_repository(entity_id, session=sess)

            if expected_label:
                cypher = (
                    f"MATCH (n:{expected_label} {{id: $entity_id}})\n"
                    f"WHERE ($repo_id IS NULL OR n.repo_id = $repo_id)\n"
                    f"RETURN properties(n) AS props"
                )
                res = sess.run(cypher, entity_id=entity_id, repo_id=repo_id).single()
                if res and "props" in res:
                    return record_to_entity(expected_label, res["props"])
                return None

            cypher = (
                "MATCH (n {id: $entity_id})\n"
                "WHERE ($repo_id IS NULL OR (n:Repository AND n.id = $repo_id) OR n.repo_id = $repo_id)\n"
                "RETURN properties(n) AS props, labels(n) AS labels"
            )
            res = sess.run(cypher, entity_id=entity_id, repo_id=repo_id).single()
            if res and "props" in res and "labels" in res:
                labels = res["labels"]
                primary_label = next((lbl for lbl in labels if lbl in ENTITY_FACTORIES), None)
                if primary_label:
                    return record_to_entity(primary_label, res["props"])
            return None
        except Neo4jRetrievalError:
            raise
        except Exception as exc:
            logger.error("Failed to retrieve entity %s: %s", entity_id, type(exc).__name__)
            raise Neo4jRetrievalError(f"Failed to retrieve entity: {type(exc).__name__}") from None
        finally:
            if is_managed:
                sess.close()

    def _get_entities_by_label(
        self,
        label: NodeLabel,
        repo_id: str,
        session: Session,
    ) -> list[Any]:
        """Internal helper retrieving all entities of a given label for a repository."""
        cypher = f"MATCH (n:{label.value} {{repo_id: $repo_id}})\nRETURN properties(n) AS props"
        result = session.run(cypher, repo_id=repo_id)
        entities = []
        for record in result:
            if "props" in record:
                entities.append(record_to_entity(label.value, record["props"]))
        return entities

    def get_files(self, repo_id: str, session: Session | None = None) -> list[File]:
        """Retrieve all File entities for a repository."""
        sess, is_managed = self._get_session(session)
        try:
            return self._get_entities_by_label(NodeLabel.FILE, repo_id, sess)
        finally:
            if is_managed:
                sess.close()

    def get_modules(self, repo_id: str, session: Session | None = None) -> list[Module]:
        """Retrieve all Module entities for a repository."""
        sess, is_managed = self._get_session(session)
        try:
            return self._get_entities_by_label(NodeLabel.MODULE, repo_id, sess)
        finally:
            if is_managed:
                sess.close()

    def get_classes(self, repo_id: str, session: Session | None = None) -> list[Class]:
        """Retrieve all Class entities for a repository."""
        sess, is_managed = self._get_session(session)
        try:
            return self._get_entities_by_label(NodeLabel.CLASS, repo_id, sess)
        finally:
            if is_managed:
                sess.close()

    def get_functions(self, repo_id: str, session: Session | None = None) -> list[Function]:
        """Retrieve all Function entities for a repository."""
        sess, is_managed = self._get_session(session)
        try:
            return self._get_entities_by_label(NodeLabel.FUNCTION, repo_id, sess)
        finally:
            if is_managed:
                sess.close()

    def get_methods(self, repo_id: str, session: Session | None = None) -> list[Method]:
        """Retrieve all Method entities for a repository."""
        sess, is_managed = self._get_session(session)
        try:
            return self._get_entities_by_label(NodeLabel.METHOD, repo_id, sess)
        finally:
            if is_managed:
                sess.close()

    def get_imports(self, repo_id: str, session: Session | None = None) -> list[Import]:
        """Retrieve all Import entities for a repository."""
        sess, is_managed = self._get_session(session)
        try:
            return self._get_entities_by_label(NodeLabel.IMPORT, repo_id, sess)
        finally:
            if is_managed:
                sess.close()

    def get_relationships(
        self,
        repo_id: str,
        rel_type: RelationshipType | str | None = None,
        source_id: str | None = None,
        target_id: str | None = None,
        session: Session | None = None,
    ) -> list[Relationship]:
        """Retrieve relationships for a repository with optional filtering."""
        if not repo_id or not isinstance(repo_id, str):
            raise ValueError("repo_id must be a non-empty string")

        sess, is_managed = self._get_session(session)
        try:
            rel_type_str = rel_type.value if isinstance(rel_type, RelationshipType) else rel_type
            type_predicate = "type(r) = $rel_type" if rel_type_str else "type(r) IN ['CONTAINS', 'IMPORTS', 'CALLS', 'INHERITS']"

            cypher = (
                f"MATCH (src)-[r]->(tgt)\n"
                f"WHERE {type_predicate}\n"
                f"  AND ((src:Repository AND src.id = $repo_id) OR src.repo_id = $repo_id)\n"
                f"  AND ((tgt:Repository AND tgt.id = $repo_id) OR tgt.repo_id = $repo_id)\n"
                f"  AND ($source_id IS NULL OR src.id = $source_id)\n"
                f"  AND ($target_id IS NULL OR tgt.id = $target_id)\n"
                f"RETURN src.id AS source_id, tgt.id AS target_id, type(r) AS rel_type, properties(r) AS properties"
            )

            res = sess.run(
                cypher,
                repo_id=repo_id,
                rel_type=rel_type_str,
                source_id=source_id,
                target_id=target_id,
            )

            relationships = []
            for record in res:
                relationships.append(
                    record_to_relationship(
                        source_id=record["source_id"],
                        target_id=record["target_id"],
                        rel_type=record["rel_type"],
                        properties=dict(record.get("properties", {})),
                    )
                )
            return relationships
        except Neo4jRetrievalError:
            raise
        except Exception as exc:
            logger.error("Failed to retrieve relationships for %s: %s", repo_id, type(exc).__name__)
            raise Neo4jRetrievalError(f"Failed to retrieve relationships: {type(exc).__name__}") from None
        finally:
            if is_managed:
                sess.close()

    def get_repository_graph(
        self,
        repo_id: str,
        session: Session | None = None,
    ) -> UnifiedCodeModel | None:
        """Retrieve the complete repository graph and reconstruct it into a UnifiedCodeModel.

        Returns None if the repository entity does not exist in Neo4j.
        """
        sess, is_managed = self._get_session(session)
        try:
            repo = self.get_repository(repo_id, session=sess)
            if repo is None:
                return None

            files = self.get_files(repo_id, session=sess)
            modules = self.get_modules(repo_id, session=sess)
            classes = self.get_classes(repo_id, session=sess)
            functions = self.get_functions(repo_id, session=sess)
            methods = self.get_methods(repo_id, session=sess)
            imports = self.get_imports(repo_id, session=sess)
            relationships = self.get_relationships(repo_id, session=sess)

            ucm = UnifiedCodeModel(repository=repo)
            for f in files:
                ucm.add_file(f)
            for m in modules:
                ucm.add_module(m)
            for c in classes:
                ucm.add_class(c)
            for fn in functions:
                ucm.add_function(fn)
            for mt in methods:
                ucm.add_method(mt)
            for im in imports:
                ucm.add_import(im)
            for rel in relationships:
                ucm.add_relationship(rel)

            logger.info(
                "Successfully reconstructed graph for repository %s (%d files, %d relationships)",
                repo_id,
                len(files),
                len(relationships),
            )
            return ucm
        finally:
            if is_managed:
                sess.close()


def get_repository_graph(
    repo_id: str,
    driver: Driver | None = None,
    session: Session | None = None,
) -> UnifiedCodeModel | None:
    """Functional convenience entry point to retrieve a full repository UCM graph."""
    retriever = GraphRetriever(driver=driver)
    return retriever.get_repository_graph(repo_id, session=session)


def get_entity_by_id(
    entity_id: str,
    repo_id: str | None = None,
    driver: Driver | None = None,
    session: Session | None = None,
) -> Any | None:
    """Functional convenience entry point to retrieve a single entity by ID."""
    retriever = GraphRetriever(driver=driver)
    return retriever.get_entity_by_id(entity_id, repo_id=repo_id, session=session)


def get_relationships(
    repo_id: str,
    rel_type: RelationshipType | str | None = None,
    driver: Driver | None = None,
    session: Session | None = None,
) -> list[Relationship]:
    """Functional convenience entry point to retrieve repository relationships."""
    retriever = GraphRetriever(driver=driver)
    return retriever.get_relationships(repo_id, rel_type=rel_type, session=session)
