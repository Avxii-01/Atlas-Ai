"""Atlas AI - FastAPI Application Entry Point."""

import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("atlas_ai")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Atlas AI backend application service",
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle standard HTTP exceptions predictably."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected application exceptions without leaking internal details."""
    logger.error("Unhandled exception on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/health", status_code=200)
def health_check() -> dict[str, str]:
    """Health check endpoint indicating application process readiness."""
    return {"status": "ok"}


# Mount API v1 routing foundation
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
