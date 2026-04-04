"""Webhook endpoints for LiveKit and Twilio events."""

import logging
from urllib.parse import parse_qsl

from fastapi import APIRouter, HTTPException, Request, status

from app.services.livekit_webhook_auth import LiveKitWebhookAuthError, LiveKitWebhookVerifier
from app.services.webhook_ingestion import WebhookIngestionService

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
LOGGER = logging.getLogger(__name__)


def get_webhook_service(request: Request) -> WebhookIngestionService:
    """Return the webhook service from app state or raise a readiness error."""

    webhook_service = getattr(request.app.state, "webhook_service", None)
    if webhook_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook storage is not available",
        )
    return webhook_service


def get_livekit_webhook_verifier(request: Request) -> LiveKitWebhookVerifier:
    """Return the LiveKit webhook verifier from app state."""

    verifier = getattr(request.app.state, "livekit_webhook_verifier", None)
    if verifier is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LiveKit webhook verification is not available",
        )
    return verifier


@router.post("/livekit", status_code=status.HTTP_202_ACCEPTED)
async def livekit_webhook(request: Request) -> dict[str, object]:
    webhook_service = get_webhook_service(request)
    verifier = get_livekit_webhook_verifier(request)
    body = await request.body()
    try:
        verifier.verify(
            body=body,
            authorization=request.headers.get("Authorization"),
        )
        payload = await request.json()
    except LiveKitWebhookAuthError as exc:
        client_host = request.client.host if request.client is not None else "unknown"
        LOGGER.warning("Rejected LiveKit webhook from %s: %s", client_host, exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    try:
        result = webhook_service.handle_livekit_event(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "status": "accepted",
        "source": result.source,
        "event_type": result.event_type,
        "duplicated": result.duplicated,
        "ignored": result.ignored,
        "room_name": result.session.room_name if result.session is not None else None,
    }


@router.post("/twilio/status", status_code=status.HTTP_202_ACCEPTED)
async def twilio_status_webhook(request: Request) -> dict[str, object]:
    webhook_service = get_webhook_service(request)
    body = await request.body()
    form_data = dict(parse_qsl(body.decode("utf-8"), keep_blank_values=True))
    try:
        result = webhook_service.handle_twilio_status(form_data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "status": "accepted",
        "source": result.source,
        "event_type": result.event_type,
        "duplicated": result.duplicated,
        "ignored": result.ignored,
        "room_name": result.session.room_name if result.session is not None else None,
    }
