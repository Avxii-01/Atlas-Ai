"""API schemas for repository analysis and status contracts."""

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
