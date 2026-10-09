"""Repository analysis orchestration service for Atlas AI (P0-18).

Coordinates the static analysis pipeline:
Repository -> Scanner -> Tree-sitter Parser -> UCM -> Resolver -> Neo4j Persistence.
"""

import logging
import os
from pathlib import Path
from typing import Any
from fastapi import HTTPException
from neo4j import Driver, Session

from app.db.entity_persister import Neo4jPersistenceError, persist_entities
from app.db.graph_retriever import GraphRetriever, Neo4jRetrievalError
from app.db.neo4j import Neo4jConnectionError, get_driver
from app.db.relationship_persister import (
    Neo4jRelationshipPersistenceError,
    persist_relationships,
    relationship_to_properties,
)
from app.db.schema import init_schema
from app.resolver import resolve_repository
from app.schemas.repository import (
    AnalysisSummary,
    NodeModel,
    RelationshipModel,
    RepositoryAnalysisRequest,
    RepositoryAnalysisResponse,
    RepositoryGraphResponse,
)
from app.ucm.model import UnifiedCodeModel

logger = logging.getLogger("atlas_ai.repository_service")

# Global flag to avoid recreating schema constraints on every single analysis request
_schema_initialized: bool = False


def reset_schema_initialization_flag() -> None:
    """Reset the schema initialized flag (primarily for testing)."""
    global _schema_initialized
    _schema_initialized = False


def ensure_schema_initialized(driver: Driver | None = None) -> None:
    """Ensure Neo4j uniqueness constraints and indexes exist without re-running on every request."""
    global _schema_initialized
    if not _schema_initialized:
        try:
            init_schema(driver=driver)
            _schema_initialized = True
            logger.info("Neo4j graph schema successfully verified/initialized.")
        except Neo4jConnectionError:
            raise
        except Exception as exc:
            logger.error("Failed to verify/initialize Neo4j schema: %s", type(exc).__name__)
            raise


def validate_repository_path(path_str: str) -> Path:
    """Validate and resolve a repository filesystem path for local analysis.

    Ensures the path exists, is a directory, is readable, and is not a protected
    system or root directory.

    Raises:
        HTTPException(status_code=400): If the path is empty, nonexistent, not a directory,
            or targets a sensitive/system location.
    """
    if not path_str or not isinstance(path_str, str) or not path_str.strip():
        raise HTTPException(status_code=400, detail="Repository path cannot be empty")

    try:
        resolved = Path(path_str.strip()).resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid repository path format")

    if not resolved.exists():
        raise HTTPException(status_code=400, detail="Repository path does not exist")

    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail="Repository path must be a directory")

    # Reject system root and sensitive operating system directories
    parts = resolved.parts
    if resolved == resolved.anchor or len(parts) <= 1:
        raise HTTPException(
            status_code=400,
            detail="Scanning root directories is not permitted",
        )

    resolved_str = str(resolved).lower()
    system_dirs = {
        "/etc",
        "/proc",
        "/sys",
        "/dev",
        "/boot",
        "/bin",
        "/sbin",
        "/usr/bin",
        "/usr/sbin",
        "c:\\windows",
        "c:\\program files",
        "c:\\program files (x86)",
        "c:\\system volume information",
    }
    for sys_dir in system_dirs:
        if resolved_str == sys_dir or resolved_str.startswith(sys_dir + os.sep):
            raise HTTPException(
                status_code=400,
                detail="Scanning system directories is not permitted",
            )

    return resolved


def validate_repository_id(repo_id: str) -> str:
    """Validate and sanitize a repository identifier.

    Args:
        repo_id: Repository ID string.

    Returns:
        Sanitized repository ID.

    Raises:
        HTTPException: 400 Bad Request if repository_id is empty, pure whitespace, or malformed.
    """
    if not isinstance(repo_id, str) or not repo_id.strip():
        raise HTTPException(status_code=400, detail="Repository ID cannot be empty")

    clean_id = repo_id.strip()

    if "\0" in clean_id or "../" in clean_id or "..\\" in clean_id:
        raise HTTPException(status_code=400, detail="Invalid repository ID format")

    if len(clean_id) > 255:
        raise HTTPException(status_code=400, detail="Repository ID exceeds maximum permitted length")

    return clean_id


def serialize_ucm_graph(
    ucm: UnifiedCodeModel,
    limit: int | None = None,
) -> tuple[list[NodeModel], list[RelationshipModel]]:
    """Serialize a UnifiedCodeModel into deterministically ordered API nodes and relationships.

    Guarantees:
    - Nodes and edges are sorted deterministically.
    - Every returned edge connects nodes present in the returned nodes list.
    - Preserves edge direction (source -> target).
    - Preserves stable UCM entity and edge identifiers.
    - Preserves location evidence and metadata.

    Args:
        ucm: UnifiedCodeModel to serialize.
        limit: Optional maximum number of nodes to include.

    Returns:
        Tuple of (serialized_nodes, serialized_relationships).
    """
    nodes: list[NodeModel] = []

    # 1. Repository root node
    if ucm.repository:
        nodes.append(
            NodeModel(
                id=ucm.repository.id,
                label="Repository",
                name=ucm.repository.name,
                type="Repository",
                display_name=ucm.repository.name,
                properties={
                    "name": ucm.repository.name,
                    "source": ucm.repository.source,
                    "created_at": ucm.repository.created_at,
                },
            )
        )

    # 2. Files
    for f in ucm.files:
        nodes.append(
            NodeModel(
                id=f.id,
                label="File",
                name=f.path,
                type="File",
                display_name=f.path,
                properties={
                    "repo_id": f.repo_id,
                    "path": f.path,
                    "language": f.language,
                    "start_line": f.start_line,
                    "end_line": f.end_line,
                    "start_byte": f.start_byte,
                    "end_byte": f.end_byte,
                },
            )
        )

    # 3. Modules
    for m in ucm.modules:
        nodes.append(
            NodeModel(
                id=m.id,
                label="Module",
                name=m.name,
                type="Module",
                display_name=m.name,
                properties={
                    "repo_id": m.repo_id,
                    "name": m.name,
                    "qualified_name": m.qualified_name,
                    "file_path": m.file_path,
                },
            )
        )

    # 4. Classes
    for c in ucm.classes:
        nodes.append(
            NodeModel(
                id=c.id,
                label="Class",
                name=c.name,
                type="Class",
                display_name=c.name,
                properties={
                    "repo_id": c.repo_id,
                    "name": c.name,
                    "qualified_name": c.qualified_name,
                    "file_path": c.file_path,
                    "language": c.language,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "start_byte": c.start_byte,
                    "end_byte": c.end_byte,
                    "docstring": c.docstring,
                },
            )
        )

    # 5. Functions
    for fn in ucm.functions:
        nodes.append(
            NodeModel(
                id=fn.id,
                label="Function",
                name=fn.name,
                type="Function",
                display_name=fn.name,
                properties={
                    "repo_id": fn.repo_id,
                    "name": fn.name,
                    "qualified_name": fn.qualified_name,
                    "file_path": fn.file_path,
                    "language": fn.language,
                    "start_line": fn.start_line,
                    "end_line": fn.end_line,
                    "start_byte": fn.start_byte,
                    "end_byte": fn.end_byte,
                    "docstring": fn.docstring,
                },
            )
        )

    # 6. Methods
    for mt in ucm.methods:
        nodes.append(
            NodeModel(
                id=mt.id,
                label="Method",
                name=mt.name,
                type="Method",
                display_name=mt.name,
                properties={
                    "repo_id": mt.repo_id,
                    "name": mt.name,
                    "qualified_name": mt.qualified_name,
                    "file_path": mt.file_path,
                    "language": mt.language,
                    "start_line": mt.start_line,
                    "end_line": mt.end_line,
                    "start_byte": mt.start_byte,
                    "end_byte": mt.end_byte,
                    "docstring": mt.docstring,
                },
            )
        )

    # 7. Imports
    for im in ucm.imports:
        nodes.append(
            NodeModel(
                id=im.id,
                label="Import",
                name=im.imported_name,
                type="Import",
                display_name=im.imported_name,
                properties={
                    "repo_id": im.repo_id,
                    "file_path": im.file_path,
                    "module_name": im.module_name,
                    "imported_name": im.imported_name,
                    "alias": im.alias,
                    "start_line": im.start_line,
                    "end_line": im.end_line,
                    "start_byte": im.start_byte,
                    "end_byte": im.end_byte,
                },
            )
        )

    # Sort nodes deterministically: Repository root node first, then by entity ID
    nodes.sort(key=lambda n: (0 if n.label == "Repository" else 1, n.id))

    # Apply limit if requested
    if limit is not None and limit > 0:
        nodes = nodes[:limit]

    valid_node_ids = {n.id for n in nodes}

    # Pre-sort relationships deterministically before assigning edge IDs
    # to guarantee identical edge IDs even if duplicate edges arrive in varied order
    def _rel_sort_key(r):
        start_l = r.location.start_point.line if r.location is not None else -1
        start_c = r.location.start_point.column if r.location is not None else -1
        meta_repr = repr(sorted(r.metadata.items())) if r.metadata else ""
        return (r.source_id, r.rel_type.value, r.target_id, start_l, start_c, meta_repr)

    sorted_raw_rels = sorted(ucm.relationships, key=_rel_sort_key)

    # Serialize relationships
    seen_edge_ids: dict[str, int] = {}
    relationships: list[RelationshipModel] = []
    for rel in sorted_raw_rels:
        # Enforce invariant: every returned edge must reference nodes present in returned nodes
        if rel.source_id not in valid_node_ids or rel.target_id not in valid_node_ids:
            continue

        props = relationship_to_properties(rel)
        base_edge_id = f"{rel.source_id}->{rel.rel_type.value}->{rel.target_id}"
        if rel.location is not None:
            base_edge_id = f"{base_edge_id}:L{rel.location.start_point.line}"

        count = seen_edge_ids.get(base_edge_id, 0)
        seen_edge_ids[base_edge_id] = count + 1
        edge_id = base_edge_id if count == 0 else f"{base_edge_id}#{count}"

        relationships.append(
            RelationshipModel(
                id=edge_id,
                source=rel.source_id,
                target=rel.target_id,
                type=rel.rel_type.value,
                source_id=rel.source_id,
                target_id=rel.target_id,
                rel_type=rel.rel_type.value,
                properties=props,
                metadata=dict(rel.metadata),
            )
        )

    # Sort relationships deterministically
    relationships.sort(key=lambda r: (r.source, r.type, r.target, r.id))

    return nodes, relationships


class RepositoryService:
    """Service orchestrating repository static analysis and graph persistence."""

    def __init__(self, driver: Driver | None = None) -> None:
        """Initialize RepositoryService with an optional Neo4j Driver."""
        self.driver = driver

    def _get_driver(self) -> Driver:
        """Acquire the active Neo4j driver or raise 503 if unavailable."""
        if self.driver is not None:
            return self.driver
        try:
            return get_driver()
        except Neo4jConnectionError:
            logger.error("Neo4j database connection unavailable during repository analysis")
            raise HTTPException(status_code=503, detail="Database service unavailable") from None
        except Exception as exc:
            logger.error("Failed to acquire Neo4j driver: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="Database service unavailable") from None

    def analyze_repository(
        self,
        request: RepositoryAnalysisRequest,
        session: Session | None = None,
    ) -> RepositoryAnalysisResponse:
        """Orchestrate the full repository static analysis and graph persistence pipeline.

        1. Validates and normalizes the repository filesystem path.
        2. Scans and parses Python files with Tree-sitter.
        3. Extracts UCM entities and structural CONTAINS relationships.
        4. Resolves semantic IMPORTS, INHERITS, and CALLS relationships.
        5. Verifies Neo4j schema constraints and indexes.
        6. Persists UCM entities into Neo4j.
        7. Persists resolved relationships into Neo4j.
        8. Returns deterministic summary response.

        Args:
            request: Typed repository analysis request parameters.
            session: Optional caller-managed Neo4j Session for testing.

        Returns:
            RepositoryAnalysisResponse matching the docs/API.md contract.

        Raises:
            HTTPException: With appropriate 400, 500, or 503 status codes.
        """
        # 1. Path validation
        repo_path = validate_repository_path(request.path or "")
        repo_name = request.name or repo_path.name
        repo_source = request.source or str(repo_path)

        # 2. Acquire database connection
        active_driver = self._get_driver()

        # 3. Ensure schema constraints/indexes exist without redundant recreation
        try:
            ensure_schema_initialized(driver=active_driver)
        except Neo4jConnectionError:
            raise HTTPException(status_code=503, detail="Database service unavailable") from None
        except Exception as exc:
            logger.error("Schema verification failed: %s", type(exc).__name__)
            raise HTTPException(status_code=500, detail="Database schema initialization failed") from None

        # 4. Invoke the static analysis and relationship resolution pipeline
        try:
            logger.info("Executing static analysis pipeline for repository at '%s'", repo_path)
            ucm = resolve_repository(
                repo_path=repo_path,
                repo_name=repo_name,
                repo_source=repo_source,
            )
        except Exception as exc:
            logger.error("Static analysis pipeline failed for %s: %s", repo_path, type(exc).__name__, exc_info=True)
            raise HTTPException(status_code=500, detail="Static analysis pipeline failed") from None

        # 5. Persist entities FIRST
        try:
            logger.info("Persisting %d entities for repository '%s'", len(ucm.files), ucm.repository.id)
            persist_entities(ucm, driver=active_driver, session=session)
        except Neo4jPersistenceError:
            logger.error("Entity persistence failed for repository '%s'", ucm.repository.id)
            raise HTTPException(status_code=500, detail="Failed to persist repository entities") from None
        except Neo4jConnectionError:
            raise HTTPException(status_code=503, detail="Database service unavailable") from None
        except Exception as exc:
            logger.error("Unexpected error during entity persistence: %s", type(exc).__name__)
            raise HTTPException(status_code=500, detail="Failed to persist repository entities") from None

        # 6. Persist relationships SECOND
        try:
            logger.info("Persisting %d relationships for repository '%s'", len(ucm.relationships), ucm.repository.id)
            persist_relationships(ucm, driver=active_driver, session=session)
        except Neo4jRelationshipPersistenceError:
            logger.error("Relationship persistence failed for repository '%s'", ucm.repository.id)
            raise HTTPException(status_code=500, detail="Failed to persist repository relationships") from None
        except Neo4jConnectionError:
            raise HTTPException(status_code=503, detail="Database service unavailable") from None
        except Exception as exc:
            logger.error("Unexpected error during relationship persistence: %s", type(exc).__name__)
            raise HTTPException(status_code=500, detail="Failed to persist repository relationships") from None

        # 7. Construct and return documented summary response
        summary = AnalysisSummary(
            files=len(ucm.files),
            classes=len(ucm.classes),
            functions=len(ucm.functions),
            relationships=len(ucm.relationships),
            modules=len(ucm.modules),
            methods=len(ucm.methods),
            imports=len(ucm.imports),
        )

        return RepositoryAnalysisResponse(
            repository_id=ucm.repository.id,
            status="completed",
            summary=summary,
        )

    def get_repository_graph(
        self,
        repository_id: str,
        session: Session | None = None,
        limit: int | None = None,
    ) -> RepositoryGraphResponse:
        """Retrieve persisted repository graph from Neo4j and return serialized nodes and edges.

        Args:
            repository_id: Stable identifier of the repository to retrieve.
            session: Optional caller-managed Neo4j Session for testing.
            limit: Optional maximum number of nodes to return.

        Returns:
            RepositoryGraphResponse matching docs/API.md contract.

        Raises:
            HTTPException:
                400: If repository_id is malformed or invalid.
                404: If repository does not exist in Neo4j.
                503: If Neo4j database is unreachable.
                500: If graph retrieval fails with an internal error.
        """
        clean_repo_id = validate_repository_id(repository_id)

        # Acquire database driver if session is not explicitly provided
        active_driver = self.driver
        if active_driver is None and session is None:
            try:
                active_driver = self._get_driver()
            except Neo4jConnectionError:
                raise HTTPException(status_code=503, detail="Database service unavailable") from None

        try:
            retriever = GraphRetriever(driver=active_driver)
            ucm = retriever.get_repository_graph(clean_repo_id, session=session)
        except Neo4jConnectionError:
            raise HTTPException(status_code=503, detail="Database service unavailable") from None
        except Exception as exc:
            logger.error(
                "Failed to retrieve repository graph for '%s': %s",
                clean_repo_id,
                type(exc).__name__,
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail="Failed to retrieve repository graph") from None

        if ucm is None:
            raise HTTPException(status_code=404, detail=f"Repository '{clean_repo_id}' not found")

        nodes, relationships = serialize_ucm_graph(ucm, limit=limit)

        return RepositoryGraphResponse(
            repository_id=clean_repo_id,
            nodes=nodes,
            relationships=relationships,
        )
