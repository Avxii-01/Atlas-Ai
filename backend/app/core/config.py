"""Application configuration module for Atlas AI."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    """Minimal application configuration settings."""

    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "Atlas AI")
    VERSION: str = os.getenv("PROJECT_VERSION", "0.1.0")
    API_V1_PREFIX: str = os.getenv("API_V1_PREFIX", "/api/v1")


settings = Settings()
