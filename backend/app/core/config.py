"""Application configuration module for Atlas AI."""

from dataclasses import dataclass, field
import os


@dataclass(frozen=True)
class Settings:
    """Minimal application configuration settings."""

    PROJECT_NAME: str = field(default_factory=lambda: os.getenv("PROJECT_NAME", "Atlas AI"))
    VERSION: str = field(default_factory=lambda: os.getenv("PROJECT_VERSION", "0.1.0"))
    API_V1_PREFIX: str = field(default_factory=lambda: os.getenv("API_V1_PREFIX", "/api/v1"))
    NEO4J_URI: str = field(default_factory=lambda: os.getenv("NEO4J_URI", "bolt://neo4j:7687"))
    NEO4J_USERNAME: str = field(default_factory=lambda: os.getenv("NEO4J_USERNAME", "neo4j"))
    NEO4J_PASSWORD: str = field(default_factory=lambda: os.getenv("NEO4J_PASSWORD", ""))


settings = Settings()
