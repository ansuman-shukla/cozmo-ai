"""Metrics endpoint."""

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.observability.metrics import record_call_session_snapshot, record_healthcheck

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics(request: Request) -> Response:
    record_healthcheck()
    session_service = getattr(request.app.state, "session_service", None)
    if session_service is not None:
        record_call_session_snapshot(session_service.list_call_sessions())
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
