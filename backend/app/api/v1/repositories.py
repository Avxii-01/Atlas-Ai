"""Repository API routes for Atlas AI v1 (P0-18)."""

from fastapi import APIRouter, Depends
from app.schemas.repository import (
    RepositoryAnalysisRequest,
    RepositoryAnalysisResponse,
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
