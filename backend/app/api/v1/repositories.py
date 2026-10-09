"""Repository API routes for Atlas AI v1 (P0-18, P0-19)."""

from fastapi import APIRouter, Depends, Query
from app.schemas.repository import (
    RepositoryAnalysisRequest,
    RepositoryAnalysisResponse,
    RepositoryGraphResponse,
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
