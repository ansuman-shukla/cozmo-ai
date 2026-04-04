"""Read APIs for call sessions and transcripts."""

from fastapi import APIRouter, HTTPException, Query, Request, status

from cozmo_contracts.models import CallSessionRecord, CallSessionStatus, TranscriptTurn

from app.services.session_service import SessionService

router = APIRouter(prefix="/calls", tags=["calls"])


def get_session_service(request: Request) -> SessionService:
    """Return the session service from app state or raise a backend readiness error."""

    session_service = getattr(request.app.state, "session_service", None)
    if session_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Session storage is not available",
        )
    return session_service


@router.get("", response_model=dict[str, list[CallSessionRecord]])
async def list_calls(
    request: Request,
    status_filter: CallSessionStatus | None = Query(default=None, alias="status"),
    did: str | None = Query(default=None),
) -> dict[str, list[CallSessionRecord]]:
    session_service = get_session_service(request)
    return {
        "items": session_service.list_call_sessions(
            status=status_filter.value if status_filter else None,
            did=did,
        )
    }


@router.get("/{room_name}", response_model=CallSessionRecord)
async def get_call(request: Request, room_name: str) -> CallSessionRecord:
    session_service = get_session_service(request)
    record = session_service.get_call_session(room_name)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call session not found")
    return record


@router.get("/{room_name}/transcript", response_model=dict[str, list[TranscriptTurn] | str])
async def get_transcript(request: Request, room_name: str) -> dict[str, list[TranscriptTurn] | str]:
    session_service = get_session_service(request)
    transcript = session_service.list_transcript(room_name)
    return {"room_name": room_name, "items": transcript}
