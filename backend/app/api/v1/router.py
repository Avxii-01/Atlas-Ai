"""API v1 root router establishing the v1 routing foundation."""

from fastapi import APIRouter

from app.api.v1.repositories import router as repositories_router

api_router = APIRouter()

# Register repositories router
api_router.include_router(repositories_router, prefix="/repositories", tags=["repositories"])
