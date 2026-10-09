"""Repository API routes for Atlas AI v1 (P0-18, P0-19, P0-20)."""

from fastapi import APIRouter, Depends, Query
from app.schemas.repository import (
    RepositoryAnalysisRequest,
    RepositoryAnalysisResponse,
    RepositoryGraphResponse,
    RepositoryImpactResponse,
)
from app.services.repository_service import RepositoryService

router = APIRouter()


def get_repository_service() -> RepositoryService:
    """Dependency provider returning a RepositoryService instance."""
    return RepositoryService()


@router.post(
    "/analyze",
    response_model=RepositoryAnalysisResponse,
    status_code=200,
    summary="Analyze repository and build code knowledge graph",
    description="Scans, parses, and resolves code entities and relationships for a repository, persisting into Neo4j.",
)
def analyze_repository(
    request: RepositoryAnalysisRequest,
    service: RepositoryService = Depends(get_repository_service),
) -> RepositoryAnalysisResponse:
    """Execute repository analysis pipeline and return deterministic summary."""
    return service.analyze_repository(request)


@router.get(
    "/{repository_id}/graph",
    response_model=RepositoryGraphResponse,
    status_code=200,
    summary="Retrieve repository code knowledge graph",
    description="Returns persisted nodes and relationships for a repository from Neo4j.",
)
def get_repository_graph(
    repository_id: str,
    limit: int | None = Query(default=None, ge=1, description="Optional maximum number of nodes to return"),
    service: RepositoryService = Depends(get_repository_service),
) -> RepositoryGraphResponse:
    """Retrieve repository graph from Neo4j and return serialized nodes and relationships."""
    return service.get_repository_graph(repository_id=repository_id, limit=limit)


@router.get(
    "/{repository_id}/impact/{entity_id:path}",
    response_model=RepositoryImpactResponse,
    status_code=200,
    summary="Perform impact analysis on a repository entity",
    description="Calculates direct and transitive blast radius of a target entity, returning impacted dependents and affected files.",
)
def get_entity_impact(
    repository_id: str,
    entity_id: str,
    max_depth: int = Query(default=10, ge=1, description="Maximum traversal depth (>= 1)"),
    service: RepositoryService = Depends(get_repository_service),
) -> RepositoryImpactResponse:
    """Perform impact analysis on an entity and return direct and transitive dependents."""
    return service.analyze_impact(
        repository_id=repository_id,
        entity_id=entity_id,
        max_depth=max_depth,
    )
