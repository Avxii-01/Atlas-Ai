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
from app.db.neo4j import Neo4jConnectionError, get_driver
from app.db.relationship_persister import (
    Neo4jRelationshipPersistenceError,
    persist_relationships,
)
from app.db.schema import init_schema
from app.resolver import resolve_repository
from app.schemas.repository import (
    AnalysisSummary,
    RepositoryAnalysisRequest,
    RepositoryAnalysisResponse,
)

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
