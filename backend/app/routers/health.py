"""Health and readiness routes."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness(request: Request) -> JSONResponse:
    mongo_ready = getattr(request.app.state, "mongo_ready", True)
    if not mongo_ready:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "mongo": "unavailable"},
        )
    return JSONResponse(content={"status": "ready"})
