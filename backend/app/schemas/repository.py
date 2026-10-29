"""API schemas for repository analysis and status contracts."""

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnalysisSummary(BaseModel):
    """Statistical summary of entities and relationships extracted from the repository."""

    model_config = ConfigDict(extra="ignore")

    files: int = Field(..., description="Number of source files analyzed")
    classes: int = Field(..., description="Number of class declarations extracted")
    functions: int = Field(..., description="Number of module-level function declarations extracted")
    relationships: int = Field(..., description="Total count of resolved and persisted relationships")
    modules: int | None = Field(default=None, description="Number of logical modules discovered")
    methods: int | None = Field(default=None, description="Number of method declarations extracted")
    imports: int | None = Field(default=None, description="Number of import statements extracted")


class RepositoryAnalysisRequest(BaseModel):
    """Request payload for POST /api/v1/repositories/analyze."""

    model_config = ConfigDict(extra="ignore")

    path: str | None = Field(default=None, description="Local filesystem path to the repository")
    repo_path: str | None = Field(default=None, description="Alternative alias for path")
    name: str | None = Field(default=None, description="Optional custom human-readable repository name")
    repo_name: str | None = Field(default=None, description="Alternative alias for name")
    source: str | None = Field(default=None, description="Optional repository source URI or origin string")

    @model_validator(mode="after")
    def validate_and_normalize(self) -> "RepositoryAnalysisRequest":
        effective_path = self.path or self.repo_path
        if not effective_path or not str(effective_path).strip():
            raise ValueError("Field 'path' (or 'repo_path') is required and cannot be empty")

        object.__setattr__(self, "path", str(effective_path).strip())

        effective_name = self.name or self.repo_name
        if effective_name and str(effective_name).strip():
            object.__setattr__(self, "name", str(effective_name).strip())

        return self


class RepositoryAnalysisResponse(BaseModel):
    """Response payload for POST /api/v1/repositories/analyze."""

    model_config = ConfigDict(extra="ignore")

    repository_id: str = Field(..., description="Deterministic stable identifier of the analyzed repository")
    status: str = Field(default="completed", description="Analysis completion status ('completed')")
    summary: AnalysisSummary = Field(..., description="Count of analyzed files, entities, and relationships")


class NodeModel(BaseModel):
    """Serialized code entity node within a repository graph."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Stable unique identifier of the entity")
    label: str = Field(..., description="Entity label/category (e.g. Repository, File, Class, Function)")
    name: str = Field(..., description="Display label or entity name")
    type: str = Field(..., description="Entity type alias matching label")
    display_name: str | None = Field(default=None, description="Human-readable display name")
    properties: dict[str, Any] = Field(default_factory=dict, description="Entity attributes and metadata")


class RelationshipModel(BaseModel):
    """Serialized relationship edge within a repository graph."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Stable deterministic edge identifier")
    source: str = Field(..., description="Source node entity identifier")
    target: str = Field(..., description="Target node entity identifier")
    type: str = Field(..., description="Relationship type (CONTAINS, IMPORTS, CALLS, INHERITS)")
    source_id: str | None = Field(default=None, description="Alias for source node ID")
    target_id: str | None = Field(default=None, description="Alias for target node ID")
    rel_type: str | None = Field(default=None, description="Alias for relationship type")
    properties: dict[str, Any] = Field(default_factory=dict, description="Relationship properties and evidence")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional relationship metadata")


class OverviewMetadata(BaseModel):
    """Pagination and truncation metadata accompanying bounded repository overview responses."""

    model_config = ConfigDict(extra="ignore")

    view: str = Field(default="overview", description="Active graph view name ('overview')")
    total_files: int = Field(..., description="Total count of files in the repository")
    returned_files: int = Field(..., description="Count of files included in this response page")
    has_more: bool = Field(..., description="Whether more file pages are available")
    truncated: bool = Field(..., description="Whether the file collection is truncated")
    offset: int = Field(..., description="Pagination offset applied")
    limit: int = Field(..., description="Pagination limit applied")


class RepositoryGraphResponse(BaseModel):
    """Response payload for GET /api/v1/repositories/{repository_id}/graph."""

    model_config = ConfigDict(extra="ignore")

    repository_id: str = Field(..., description="Deterministic repository identifier")
    nodes: list[NodeModel] = Field(default_factory=list, description="List of graph nodes")
    relationships: list[RelationshipModel] = Field(default_factory=list, description="List of graph relationship edges")
    metadata: OverviewMetadata | None = Field(default=None, description="Overview pagination and truncation metadata")


class EntityChildrenResponse(BaseModel):
    """Response payload for GET /api/v1/repositories/{repository_id}/entities/{entity_id}/children."""

    model_config = ConfigDict(extra="ignore")

    repository_id: str = Field(..., description="Deterministic repository identifier")
    parent_id: str = Field(..., description="Stable unique identifier of the parent entity")
    parent: NodeModel = Field(..., description="Serialized parent node")
    children: list[NodeModel] = Field(default_factory=list, description="Direct children nodes")
    relationships: list[RelationshipModel] = Field(default_factory=list, description="Connecting CONTAINS relationships")
    total_children: int = Field(..., description="Total count of direct children in repository")
    returned_children: int = Field(..., description="Count of children included in this page")
    has_more: bool = Field(..., description="Whether additional children pages are available")
    truncated: bool = Field(..., description="Whether the children collection is truncated")
    offset: int = Field(..., description="Pagination offset applied")
    limit: int = Field(..., description="Pagination limit applied")


class EntityNeighborsResponse(BaseModel):
    """Response payload for GET /api/v1/repositories/{repository_id}/entities/{entity_id}/neighbors."""

    model_config = ConfigDict(extra="ignore")

    repository_id: str = Field(..., description="Deterministic repository identifier")
    entity_id: str = Field(..., description="Stable unique identifier of the target center entity")
    center: NodeModel = Field(..., description="Serialized center node")
    neighbors: list[NodeModel] = Field(default_factory=list, description="Distinct neighboring entity nodes")
    relationships: list[RelationshipModel] = Field(default_factory=list, description="Incident relationship edges")
    total_relationships: int = Field(..., description="Total count of matching incident relationships")
    returned_relationships: int = Field(..., description="Count of relationship edges in this page")
    total_neighbors: int = Field(..., description="Total count of distinct neighboring entities")
    returned_neighbors: int = Field(..., description="Count of distinct neighboring entities in this page")
    direction: str = Field(..., description="Relationship direction filter ('incoming', 'outgoing', 'both')")
    has_more: bool = Field(..., description="Whether additional relationship pages are available")
    truncated: bool = Field(..., description="Whether the relationship collection is truncated")
    offset: int = Field(..., description="Pagination offset applied")
    limit: int = Field(..., description="Pagination limit applied")


class EntitySearchResponse(BaseModel):
    """Response payload for GET /api/v1/repositories/{repository_id}/entities/search."""

    model_config = ConfigDict(extra="ignore")

    repository_id: str = Field(..., description="Deterministic repository identifier")
    query: str = Field(..., description="Active search query string")
    entities: list[NodeModel] = Field(default_factory=list, description="Matching entity nodes")
    results: list[NodeModel] = Field(default_factory=list, description="Alias matching entities")
    total_matches: int = Field(..., description="Total count of matching entities in repository")
    returned_matches: int = Field(..., description="Count of matching entities returned in this page")
    has_more: bool = Field(..., description="Whether additional result pages are available")
    truncated: bool = Field(..., description="Whether the result collection is truncated")
    offset: int = Field(..., description="Pagination offset applied")
    limit: int = Field(..., description="Pagination limit applied")
    type_filter: str | None = Field(default=None, description="Optional entity type filter applied")

    @model_validator(mode="before")
    @classmethod
    def sync_entities_and_results(cls, data: Any) -> Any:
        if isinstance(data, dict):
            ents = data.get("entities")
            res = data.get("results")
            if ents is not None and res is None:
                data["results"] = ents
            elif res is not None and ents is None:
                data["entities"] = res
        return data


class TargetEntityModel(BaseModel):
    """Target entity model whose impact is analyzed."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Stable unique identifier of the target entity")
    name: str = Field(..., description="Name or identifier of the target entity")
    label: str | None = Field(default=None, description="Entity label/kind (e.g. Function, Class)")
    type: str | None = Field(default=None, description="Entity type alias matching label")
    file_path: str | None = Field(default=None, description="Source file path containing entity")
    properties: dict[str, Any] = Field(default_factory=dict, description="Entity attributes")


class ImpactedEntityModel(BaseModel):
    """Entity affected directly or transitively by modifications to target entity."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(..., description="Stable unique identifier of the impacted entity")
    name: str = Field(..., description="Name or identifier of the impacted entity")
    depth: int = Field(..., description="Shortest-path traversal distance (hop count) from target")
    label: str | None = Field(default=None, description="Entity label/kind (e.g. Function, Class, Method)")
    type: str | None = Field(default=None, description="Entity type alias matching label")
    file_path: str | None = Field(default=None, description="Source file path containing entity")
    entity_id: str | None = Field(default=None, description="Alias matching id")
    properties: dict[str, Any] = Field(default_factory=dict, description="Entity attributes")


class AffectedFileModel(BaseModel):
    """Structured representation of a source file containing impacted entities."""

    model_config = ConfigDict(extra="ignore")

    file_id: str = Field(..., description="Deterministic File entity identifier")
    path: str = Field(..., description="Normalized repository-relative file path")


class RepositoryImpactResponse(BaseModel):
    """Response payload for GET /api/v1/repositories/{repository_id}/impact/{entity_id}."""

    model_config = ConfigDict(extra="ignore")

    entity: TargetEntityModel = Field(..., description="Target code entity whose impact was analyzed")
    direct_dependents: list[ImpactedEntityModel] = Field(
        default_factory=list,
        description="Entities directly dependent on target entity (hop depth == 1)",
    )
    transitive_dependents: list[ImpactedEntityModel] = Field(
        default_factory=list,
        description="Entities transitively dependent on target entity (hop depth > 1)",
    )
    affected_files: list[str] = Field(
        default_factory=list,
        description="Deduplicated repository-relative file paths containing impacted entities, sorted deterministically",
    )
    max_depth: int = Field(..., description="Maximum traversal depth applied during analysis")
    repository_id: str | None = Field(
        default=None,
        description="Repository identifier scoping the impact analysis",
    )
