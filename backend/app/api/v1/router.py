"""API v1 root router establishing the v1 routing foundation."""

from fastapi import APIRouter

api_router = APIRouter()

# Future P0 routers will be registered here:
# - P0-18: /repositories/analyze
# - P0-19: /repositories/{repository_id}/graph
# - P0-20: /repositories/{repository_id}/impact/{entity_id}
