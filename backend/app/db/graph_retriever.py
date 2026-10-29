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
    if label in (
        NodeLabel.FILE.value,
        NodeLabel.IMPORT.value,
        NodeLabel.CLASS.value,
        NodeLabel.FUNCTION.value,
        NodeLabel.METHOD.value,
    ):
        clean_props.setdefault("start_byte", 0)
        clean_props.setdefault("end_byte", 0)

    return factory.from_dict(clean_props)


def _primary_label(labels: list[str] | None) -> str:
    """Extract primary UCM entity label from a list of Neo4j node labels."""
    if not labels:
        return NodeLabel.FILE.value
    valid_labels = {
        NodeLabel.REPOSITORY.value,
        NodeLabel.FILE.value,
        NodeLabel.MODULE.value,
        NodeLabel.CLASS.value,
        NodeLabel.FUNCTION.value,
        NodeLabel.METHOD.value,
        NodeLabel.IMPORT.value,
    }
    for lab in labels:
        if lab in valid_labels:
            return lab
    return labels[0]


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
            if res and res.get("props") is not None:
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
                if res and res.get("props") is not None:
                    return record_to_entity(expected_label, res["props"])
                return None

            cypher = (
                "MATCH (n {id: $entity_id})\n"
                "WHERE ($repo_id IS NULL OR (n:Repository AND n.id = $repo_id) OR n.repo_id = $repo_id)\n"
                "RETURN properties(n) AS props, labels(n) AS labels"
            )
            res = sess.run(cypher, entity_id=entity_id, repo_id=repo_id).single()
            if res and res.get("props") is not None and res.get("labels") is not None:
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
            if record and record.get("props") is not None:
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

    def get_repository_overview(
        self,
        repo_id: str,
        limit: int = 50,
        offset: int = 0,
        session: Session | None = None,
    ) -> tuple[Repository, list[File], list[Relationship], int] | None:
        """Retrieve bounded repository overview containing Repository root and paged File nodes.

        Executes a single parameterized Cypher query with database-side bounding.
        Returns None if repository does not exist.
        """
        if not repo_id or not isinstance(repo_id, str):
            raise ValueError("repo_id must be a non-empty string")

        sess, is_managed = self._get_session(session)
        try:
            cypher = (
                "MATCH (r:Repository {id: $repo_id})\n"
                "CALL {\n"
                "  WITH r\n"
                "  OPTIONAL MATCH (r)-[:CONTAINS]->(f_count:File {repo_id: $repo_id})\n"
                "  RETURN count(f_count) AS total_files\n"
                "}\n"
                "CALL {\n"
                "  WITH r\n"
                "  OPTIONAL MATCH (r)-[rel:CONTAINS]->(f:File {repo_id: $repo_id})\n"
                "  WHERE f IS NOT NULL\n"
                "  WITH rel, f\n"
                "  ORDER BY f.path ASC\n"
                "  SKIP $offset\n"
                "  LIMIT $limit\n"
                "  RETURN collect(properties(f)) AS files,\n"
                "         collect({\n"
                "           source_id: r.id,\n"
                "           target_id: f.id,\n"
                "           rel_type: type(rel),\n"
                "           properties: properties(rel)\n"
                "         }) AS edges\n"
                "}\n"
                "RETURN\n"
                "  properties(r) AS repo_props,\n"
                "  total_files,\n"
                "  files,\n"
                "  edges"
            )
            res = sess.run(
                cypher,
                repo_id=repo_id,
                offset=int(offset),
                limit=int(limit),
            ).single()

            if res is None or res.get("repo_props") is None:
                return None

            repo = record_to_entity(NodeLabel.REPOSITORY.value, res["repo_props"])
            total_files = int(res.get("total_files", 0))

            files: list[File] = []
            for f_props in res.get("files") or []:
                if f_props:
                    files.append(record_to_entity(NodeLabel.FILE.value, f_props))

            relationships: list[Relationship] = []
            for edge_dict in res.get("edges") or []:
                if edge_dict and edge_dict.get("source_id") and edge_dict.get("target_id"):
                    relationships.append(
                        record_to_relationship(
                            source_id=edge_dict["source_id"],
                            target_id=edge_dict["target_id"],
                            rel_type=edge_dict["rel_type"],
                            properties=dict(edge_dict.get("properties") or {}),
                        )
                    )

            logger.info(
                "Retrieved overview for repository %s (%d files returned of %d total)",
                repo_id,
                len(files),
                total_files,
            )
            return repo, files, relationships, total_files
        except Neo4jRetrievalError:
            raise
        except Exception as exc:
            logger.error("Failed to retrieve repository overview for %s: %s", repo_id, type(exc).__name__)
            raise Neo4jRetrievalError(f"Failed to retrieve repository overview: {type(exc).__name__}") from None
        finally:
            if is_managed:
                sess.close()

    def get_entity_children(
        self,
        repo_id: str,
        entity_id: str,
        limit: int = 50,
        offset: int = 0,
        session: Session | None = None,
    ) -> dict[str, Any]:
        """Retrieve direct CONTAINS children of an entity in a repository.

        Executes a single parameterized Cypher query with database-side bounding.
        Returns a dictionary with:
            - repo_exists: bool
            - parent: UCM entity or None
            - children: list of child UCM entities
            - edges: list of relationship edge dictionaries
            - total_children: int
        """
        if not repo_id or not isinstance(repo_id, str):
            raise ValueError("repo_id must be a non-empty string")
        if not entity_id or not isinstance(entity_id, str):
            raise ValueError("entity_id must be a non-empty string")

        sess, is_managed = self._get_session(session)
        try:
            cypher = (
                "OPTIONAL MATCH (r:Repository {id: $repo_id})\n"
                "OPTIONAL MATCH (parent)\n"
                "WHERE ((parent:Repository AND parent.id = $repo_id) OR parent.repo_id = $repo_id)\n"
                "  AND parent.id = $entity_id\n"
                "CALL {\n"
                "  WITH parent, r\n"
                "  OPTIONAL MATCH (parent)-[:CONTAINS]->(child_count)\n"
                "  WHERE parent IS NOT NULL AND r IS NOT NULL AND child_count.repo_id = r.id\n"
                "  RETURN count(child_count) AS total_children\n"
                "}\n"
                "CALL {\n"
                "  WITH parent, r\n"
                "  OPTIONAL MATCH (parent)-[rel:CONTAINS]->(child)\n"
                "  WHERE parent IS NOT NULL AND r IS NOT NULL AND child IS NOT NULL AND child.repo_id = r.id\n"
                "  WITH parent, rel, child\n"
                "  ORDER BY coalesce(child.start_line, 0) ASC, child.id ASC\n"
                "  SKIP $offset\n"
                "  LIMIT $limit\n"
                "  RETURN collect(properties(child)) AS children_props,\n"
                "         collect(labels(child)) AS children_labels,\n"
                "         collect({\n"
                "           source_id: parent.id,\n"
                "           target_id: child.id,\n"
                "           rel_type: type(rel),\n"
                "           properties: properties(rel)\n"
                "         }) AS edges\n"
                "}\n"
                "RETURN\n"
                "  r IS NOT NULL AS repo_exists,\n"
                "  properties(parent) AS parent_props,\n"
                "  labels(parent) AS parent_labels,\n"
                "  total_children,\n"
                "  children_props,\n"
                "  children_labels,\n"
                "  edges"
            )

            res = sess.run(
                cypher,
                repo_id=repo_id,
                entity_id=entity_id,
                offset=int(offset),
                limit=int(limit),
            ).single()

            if res is None:
                return {
                    "repo_exists": False,
                    "parent": None,
                    "children": [],
                    "edges": [],
                    "total_children": 0,
                }

            repo_exists = bool(res.get("repo_exists", False))
            parent_props = res.get("parent_props")
            parent_labels = res.get("parent_labels") or []

            if not repo_exists or parent_props is None:
                return {
                    "repo_exists": repo_exists,
                    "parent": None,
                    "children": [],
                    "edges": [],
                    "total_children": 0,
                }

            parent_label = _primary_label(parent_labels)
            parent_entity = record_to_entity(parent_label, parent_props)
            total_children = int(res.get("total_children", 0))

            children_props = res.get("children_props") or []
            children_labels = res.get("children_labels") or []
            edges = res.get("edges") or []

            children: list[Any] = []
            for props, labels_list in zip(children_props, children_labels):
                if props:
                    child_label = _primary_label(labels_list)
                    children.append(record_to_entity(child_label, props))

            logger.info(
                "Retrieved %d children for entity %s in %s (of %d total)",
                len(children),
                entity_id,
                repo_id,
                total_children,
            )
            return {
                "repo_exists": True,
                "parent": parent_entity,
                "children": children,
                "edges": edges,
                "total_children": total_children,
            }
        except Neo4jRetrievalError:
            raise
        except Exception as exc:
            logger.error("Failed to retrieve entity children for %s in %s: %s", entity_id, repo_id, type(exc).__name__)
            raise Neo4jRetrievalError(f"Failed to retrieve entity children: {type(exc).__name__}") from None
        finally:
            if is_managed:
                sess.close()

    def get_entity_neighbors(
        self,
        repo_id: str,
        entity_id: str,
        direction: str = "both",
        types: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
        session: Session | None = None,
    ) -> dict[str, Any]:
        """Retrieve direct incident neighbors and relationships of an entity in a repository.

        Executes a single parameterized Cypher query with database-side bounding.
        Returns a dictionary with:
            - repo_exists: bool
            - center: UCM entity or None
            - neighbors: list of neighboring UCM entities
            - edges: list of relationship edge dictionaries
            - total_relationships: int
            - total_neighbors: int
        """
        if not repo_id or not isinstance(repo_id, str):
            raise ValueError("repo_id must be a non-empty string")
        if not entity_id or not isinstance(entity_id, str):
            raise ValueError("entity_id must be a non-empty string")

        clean_direction = direction.strip().lower() if isinstance(direction, str) else "both"
        if clean_direction not in ("incoming", "outgoing", "both"):
            raise ValueError(f"Invalid direction '{direction}'. Must be 'incoming', 'outgoing', or 'both'")

        allowed_types = ["CONTAINS", "IMPORTS", "CALLS", "INHERITS"]
        if types is not None and len(types) > 0:
            effective_types = [t.upper() for t in types if t.upper() in allowed_types]
            if not effective_types:
                effective_types = allowed_types
        else:
            effective_types = allowed_types

        if clean_direction == "outgoing":
            rel_pattern = "(center)-[r]->(nbr)"
        elif clean_direction == "incoming":
            rel_pattern = "(center)<-[r]-(nbr)"
        else:
            rel_pattern = "(center)-[r]-(nbr)"

        sess, is_managed = self._get_session(session)
        try:
            cypher = (
                f"OPTIONAL MATCH (r:Repository {{id: $repo_id}})\n"
                f"OPTIONAL MATCH (center)\n"
                f"WHERE ((center:Repository AND center.id = $repo_id) OR center.repo_id = $repo_id)\n"
                f"  AND center.id = $entity_id\n"
                f"CALL {{\n"
                f"  WITH center, r\n"
                f"  OPTIONAL MATCH {rel_pattern}\n"
                f"  WHERE center IS NOT NULL AND r IS NOT NULL\n"
                f"    AND type(r) IN $allowed_types\n"
                f"    AND ((nbr:Repository AND nbr.id = r.id) OR nbr.repo_id = r.id)\n"
                f"  RETURN count(DISTINCT r) AS total_relationships,\n"
                f"         count(DISTINCT (CASE WHEN nbr = center THEN NULL ELSE nbr END)) AS total_neighbors\n"
                f"}}\n"
                f"CALL {{\n"
                f"  WITH center, r\n"
                f"  OPTIONAL MATCH {rel_pattern}\n"
                f"  WHERE center IS NOT NULL AND r IS NOT NULL\n"
                f"    AND type(r) IN $allowed_types\n"
                f"    AND ((nbr:Repository AND nbr.id = r.id) OR nbr.repo_id = r.id)\n"
                f"  WITH DISTINCT center, r, startNode(r) AS src, endNode(r) AS tgt,\n"
                f"       (CASE WHEN startNode(r) = center THEN endNode(r) ELSE startNode(r) END) AS nbr\n"
                f"  WHERE r IS NOT NULL\n"
                f"  ORDER BY src.id ASC, type(r) ASC, tgt.id ASC, coalesce(r.start_line, 0) ASC, coalesce(r.start_byte, 0) ASC\n"
                f"  SKIP $offset\n"
                f"  LIMIT $limit\n"
                f"  WITH collect({{\n"
                f"         source_id: src.id,\n"
                f"         target_id: tgt.id,\n"
                f"         rel_type: type(r),\n"
                f"         properties: properties(r)\n"
                f"       }}) AS edges,\n"
                f"       collect(DISTINCT (CASE WHEN nbr = center THEN NULL ELSE nbr END)) AS paged_nbrs\n"
                f"  RETURN\n"
                f"    edges,\n"
                f"    [n IN paged_nbrs WHERE n IS NOT NULL | properties(n)] AS neighbor_props,\n"
                f"    [n IN paged_nbrs WHERE n IS NOT NULL | labels(n)] AS neighbor_labels\n"
                f"}}\n"
                f"RETURN\n"
                f"  r IS NOT NULL AS repo_exists,\n"
                f"  properties(center) AS center_props,\n"
                f"  labels(center) AS center_labels,\n"
                f"  total_relationships,\n"
                f"  total_neighbors,\n"
                f"  edges,\n"
                f"  neighbor_props,\n"
                f"  neighbor_labels"
            )

            res = sess.run(
                cypher,
                repo_id=repo_id,
                entity_id=entity_id,
                allowed_types=effective_types,
                offset=int(offset),
                limit=int(limit),
            ).single()

            if res is None:
                return {
                    "repo_exists": False,
                    "center": None,
                    "neighbors": [],
                    "edges": [],
                    "total_relationships": 0,
                    "total_neighbors": 0,
                }

            repo_exists = bool(res.get("repo_exists", False))
            center_props = res.get("center_props")
            center_labels = res.get("center_labels") or []

            if not repo_exists or center_props is None:
                return {
                    "repo_exists": repo_exists,
                    "center": None,
                    "neighbors": [],
                    "edges": [],
                    "total_relationships": 0,
                    "total_neighbors": 0,
                }

            center_label = _primary_label(center_labels)
            center_entity = record_to_entity(center_label, center_props)
            total_relationships = int(res.get("total_relationships", 0))
            total_neighbors = int(res.get("total_neighbors", 0))

            neighbor_props = res.get("neighbor_props") or []
            neighbor_labels = res.get("neighbor_labels") or []
            edges = res.get("edges") or []

            neighbors: list[Any] = []
            for props, labels_list in zip(neighbor_props, neighbor_labels):
                if props:
                    nbr_label = _primary_label(labels_list)
                    neighbors.append(record_to_entity(nbr_label, props))

            logger.info(
                "Retrieved %d relationships (%d neighbors) for entity %s in %s (of %d total relationships)",
                len(edges),
                len(neighbors),
                entity_id,
                repo_id,
                total_relationships,
            )
            return {
                "repo_exists": True,
                "center": center_entity,
                "neighbors": neighbors,
                "edges": edges,
                "total_relationships": total_relationships,
                "total_neighbors": total_neighbors,
            }
        except Neo4jRetrievalError:
            raise
        except Exception as exc:
            logger.error("Failed to retrieve entity neighbors for %s in %s: %s", entity_id, repo_id, type(exc).__name__)
            raise Neo4jRetrievalError(f"Failed to retrieve entity neighbors: {type(exc).__name__}") from None
        finally:
            if is_managed:
                sess.close()

    def search_entities(
        self,
        repo_id: str,
        q: str,
        entity_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
        session: Session | None = None,
    ) -> dict[str, Any]:
        """Search entities within a repository by case-insensitive text match.

        Executes a single parameterized Cypher query with database-side bounding.
        Matches against entity name, qualified name, path, file path, imported name, and ID.
        Applies deterministic relevance ranking (exact match, prefix match, substring match)
        with stable entity ID tie-breaker.

        Returns a dictionary with:
            - repo_exists: bool
            - entities: list of matching UCM entities
            - total_matches: int
        """
        if not repo_id or not isinstance(repo_id, str):
            raise ValueError("repo_id must be a non-empty string")
        if not q or not isinstance(q, str) or not q.strip():
            raise ValueError("q must be a non-empty string")

        clean_q = q.strip()
        q_lower = clean_q.lower()

        sess, is_managed = self._get_session(session)
        try:
            cypher = (
                "OPTIONAL MATCH (r:Repository {id: $repo_id})\n"
                "CALL {\n"
                "  WITH r\n"
                "  OPTIONAL MATCH (n)\n"
                "  WHERE r IS NOT NULL\n"
                "    AND ((n:Repository AND n.id = r.id) OR n.repo_id = r.id)\n"
                "    AND ($type_filter IS NULL OR $type_filter IN labels(n))\n"
                "    AND (\n"
                "      (n.name IS NOT NULL AND toLower(n.name) CONTAINS $q_lower) OR\n"
                "      (n.qualified_name IS NOT NULL AND toLower(n.qualified_name) CONTAINS $q_lower) OR\n"
                "      (n.path IS NOT NULL AND toLower(n.path) CONTAINS $q_lower) OR\n"
                "      (n.file_path IS NOT NULL AND toLower(n.file_path) CONTAINS $q_lower) OR\n"
                "      (n.imported_name IS NOT NULL AND toLower(n.imported_name) CONTAINS $q_lower) OR\n"
                "      (n.id IS NOT NULL AND toLower(n.id) CONTAINS $q_lower) OR\n"
                "      (n.display_name IS NOT NULL AND toLower(n.display_name) CONTAINS $q_lower)\n"
                "    )\n"
                "  RETURN count(n) AS total_matches\n"
                "}\n"
                "CALL {\n"
                "  WITH r\n"
                "  OPTIONAL MATCH (n)\n"
                "  WHERE r IS NOT NULL\n"
                "    AND ((n:Repository AND n.id = r.id) OR n.repo_id = r.id)\n"
                "    AND ($type_filter IS NULL OR $type_filter IN labels(n))\n"
                "    AND (\n"
                "      (n.name IS NOT NULL AND toLower(n.name) CONTAINS $q_lower) OR\n"
                "      (n.qualified_name IS NOT NULL AND toLower(n.qualified_name) CONTAINS $q_lower) OR\n"
                "      (n.path IS NOT NULL AND toLower(n.path) CONTAINS $q_lower) OR\n"
                "      (n.file_path IS NOT NULL AND toLower(n.file_path) CONTAINS $q_lower) OR\n"
                "      (n.imported_name IS NOT NULL AND toLower(n.imported_name) CONTAINS $q_lower) OR\n"
                "      (n.id IS NOT NULL AND toLower(n.id) CONTAINS $q_lower) OR\n"
                "      (n.display_name IS NOT NULL AND toLower(n.display_name) CONTAINS $q_lower)\n"
                "    )\n"
                "  WITH n,\n"
                "       CASE\n"
                "         WHEN toLower(coalesce(n.name, n.path, n.imported_name, '')) = $q_lower THEN 1\n"
                "         WHEN toLower(coalesce(n.name, n.qualified_name, n.path, n.imported_name, '')) STARTS WITH $q_lower THEN 2\n"
                "         ELSE 3\n"
                "       END AS rank\n"
                "  ORDER BY rank ASC, coalesce(n.path, n.file_path, '') ASC, coalesce(n.name, n.imported_name, '') ASC, n.id ASC\n"
                "  SKIP $offset\n"
                "  LIMIT $limit\n"
                "  RETURN collect(properties(n)) AS entities_props,\n"
                "         collect(labels(n)) AS entities_labels\n"
                "}\n"
                "RETURN\n"
                "  r IS NOT NULL AS repo_exists,\n"
                "  total_matches,\n"
                "  entities_props,\n"
                "  entities_labels"
            )

            res = sess.run(
                cypher,
                repo_id=repo_id,
                q_lower=q_lower,
                type_filter=entity_type,
                offset=int(offset),
                limit=int(limit),
            ).single()

            if res is None:
                return {
                    "repo_exists": False,
                    "entities": [],
                    "total_matches": 0,
                }

            repo_exists = bool(res.get("repo_exists", False))
            if not repo_exists:
                return {
                    "repo_exists": False,
                    "entities": [],
                    "total_matches": 0,
                }

            total_matches = int(res.get("total_matches", 0))
            entities_props = res.get("entities_props") or []
            entities_labels = res.get("entities_labels") or []

            entities: list[Any] = []
            for props, labels_list in zip(entities_props, entities_labels):
                if props:
                    label = _primary_label(labels_list)
                    entities.append(record_to_entity(label, props))

            logger.info(
                "Searched repository %s for '%s' (type=%s): %d returned of %d matches",
                repo_id,
                clean_q,
                entity_type,
                len(entities),
                total_matches,
            )
            return {
                "repo_exists": True,
                "entities": entities,
                "total_matches": total_matches,
            }
        except Neo4jRetrievalError:
            raise
        except Exception as exc:
            logger.error("Failed to search entities in %s for '%s': %s", repo_id, clean_q, type(exc).__name__)
            raise Neo4jRetrievalError(f"Failed to search entities: {type(exc).__name__}") from None
        finally:
            if is_managed:
                sess.close()


def get_repository_overview(
    repo_id: str,
    limit: int = 50,
    offset: int = 0,
    driver: Driver | None = None,
    session: Session | None = None,
) -> tuple[Repository, list[File], list[Relationship], int] | None:
    """Functional convenience entry point to retrieve a bounded repository overview."""
    retriever = GraphRetriever(driver=driver)
    return retriever.get_repository_overview(repo_id, limit=limit, offset=offset, session=session)


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


def get_entity_children(
    repo_id: str,
    entity_id: str,
    limit: int = 50,
    offset: int = 0,
    driver: Driver | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """Functional convenience entry point to retrieve direct children of an entity."""
    retriever = GraphRetriever(driver=driver)
    return retriever.get_entity_children(repo_id, entity_id, limit=limit, offset=offset, session=session)


def get_entity_neighbors(
    repo_id: str,
    entity_id: str,
    direction: str = "both",
    types: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
    driver: Driver | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """Functional convenience entry point to retrieve direct neighbors of an entity."""
    retriever = GraphRetriever(driver=driver)
    return retriever.get_entity_neighbors(
        repo_id=repo_id,
        entity_id=entity_id,
        direction=direction,
        types=types,
        limit=limit,
        offset=offset,
        session=session,
    )



def search_entities(
    repo_id: str,
    q: str,
    entity_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    driver: Driver | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    """Functional convenience entry point to search entities in a repository."""
    retriever = GraphRetriever(driver=driver)
    return retriever.search_entities(
        repo_id=repo_id,
        q=q,
        entity_type=entity_type,
        limit=limit,
        offset=offset,
        session=session,
    )
