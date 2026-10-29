"""Repository API routes for Atlas AI v1 (P0-18, P0-19, P0-20)."""

from typing import Literal
from fastapi import APIRouter, Depends, Query
from app.schemas.repository import (
    EntityChildrenResponse,
    EntityNeighborsResponse,
    EntitySearchResponse,
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
    description="Returns persisted nodes and relationships for a repository from Neo4j. Supports 'view=overview' for a bounded initial view.",
)
def get_repository_graph(
    repository_id: str,
    view: str | None = Query(default=None, description="Optional view filter ('overview')"),
    limit: int | None = Query(default=None, ge=1, description="Optional maximum number of nodes to return for full graph, or maximum file entities for overview (max 200)"),
    offset: int = Query(default=0, ge=0, description="Optional pagination offset for file entities in overview mode"),
    service: RepositoryService = Depends(get_repository_service),
) -> RepositoryGraphResponse:
    """Retrieve repository graph from Neo4j and return serialized nodes and relationships."""
    return service.get_repository_graph(
        repository_id=repository_id,
        limit=limit,
        view=view,
        offset=offset,
    )


@router.get(
    "/{repository_id}/entities/search",
    response_model=EntitySearchResponse,
    status_code=200,
    summary="Search entities within a repository",
    description="Searches code entities within a repository by case-insensitive text match with pagination and deterministic ordering.",
)
def search_entities(
    repository_id: str,
    q: str = Query(..., min_length=1, max_length=100, description="Non-empty search query string"),
    type: str | None = Query(default=None, description="Optional entity type/label filter (e.g. Class, Function, File)"),
    limit: int = Query(default=50, ge=1, le=200, description="Maximum number of entities to return (default 50, max 200)"),
    offset: int = Query(default=0, ge=0, description="Pagination offset (default 0)"),
    service: RepositoryService = Depends(get_repository_service),
) -> EntitySearchResponse:
    """Search code entities within a repository by text query."""
    return service.search_entities(
        repository_id=repository_id,
        q=q,
        entity_type=type,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{repository_id}/entities/{entity_id:path}/children",
    response_model=EntityChildrenResponse,
    status_code=200,
    summary="Retrieve direct structural children of an entity",
    description="Returns direct children connected via outgoing CONTAINS relationships with pagination and deterministic ordering.",
)
def get_entity_children(
    repository_id: str,
    entity_id: str,
    limit: int = Query(default=50, ge=1, le=200, description="Maximum number of children to return (default 50, max 200)"),
    offset: int = Query(default=0, ge=0, description="Pagination offset for children (default 0)"),
    service: RepositoryService = Depends(get_repository_service),
) -> EntityChildrenResponse:
    """Retrieve direct CONTAINS children of an entity."""
    return service.get_entity_children(
        repository_id=repository_id,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{repository_id}/entities/{entity_id:path}/neighbors",
    response_model=EntityNeighborsResponse,
    status_code=200,
    summary="Retrieve direct graph neighbors of an entity",
    description="Returns incident relationships and neighboring entities in the specified direction ('incoming', 'outgoing', 'both') with pagination and deterministic ordering.",
)
def get_entity_neighbors(
    repository_id: str,
    entity_id: str,
    direction: Literal["incoming", "outgoing", "both"] = Query(
        default="both",
        description="Relationship direction: 'incoming', 'outgoing', or 'both'",
    ),
    types: str | None = Query(
        default=None,
        description="Optional comma-separated relationship types ('CONTAINS,CALLS')",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of relationships to return (default 50, max 200)",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Pagination offset for relationships (default 0)",
    ),
    service: RepositoryService = Depends(get_repository_service),
) -> EntityNeighborsResponse:
    """Retrieve direct incident neighbors and relationships of an entity."""
    return service.get_entity_neighbors(
        repository_id=repository_id,
        entity_id=entity_id,
        direction=direction,
        types=types,
        limit=limit,
        offset=offset,
    )


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
