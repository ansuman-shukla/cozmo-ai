"""Webhook ingestion and call-session update logic."""

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import hashlib
import json
from typing import Any, Mapping

from cozmo_contracts.events import EventSource
from cozmo_contracts.models import (
    CallDisposition,
    CallMetricsSummary,
    CallSessionRecord,
    CallSessionStatus,
    VoiceQualityMetrics,
)

from app.services.agent_config_service import AgentConfigService
from app.services.session_service import SessionService
from app.services.telephony import is_sip_participant, parse_sip_attributes

FALLBACK_AGENT_CONFIG_ID = "fallback-unmapped-did"
PENDING_AGENT_CONFIG_ID = "pending-assignment"


@dataclass(slots=True)
class WebhookResult:
    """Outcome of a webhook ingestion attempt."""

    source: str
    event_type: str
    accepted: bool
    duplicated: bool = False
    ignored: bool = False
    session: CallSessionRecord | None = None


@dataclass(slots=True)
class WebhookEventDeduplicator:
    """Abstract deduplicator protocol implemented by a repository."""

    repository: Any

    def claim(self, *, source: EventSource, event_id: str, metadata: dict[str, Any] | None = None) -> bool:
        """Claim an event id for first-time processing."""

        return self.repository.claim(source=source.value, event_id=event_id, metadata=metadata or {})


@dataclass(slots=True)
class WebhookIngestionService:
    """Ingest LiveKit and Twilio webhook payloads into `call_sessions`."""

    session_service: SessionService
    agent_config_service: AgentConfigService
    deduplicator: WebhookEventDeduplicator

    def handle_livekit_event(self, payload: Mapping[str, Any]) -> WebhookResult:
        """Process a LiveKit webhook payload and persist the corresponding session update."""

        event_id = str(payload.get("id") or "").strip()
        event_type = str(payload.get("event") or "").strip()
        room = payload.get("room") or {}
        room_name = str(room.get("name") or "").strip()
        if not event_id or not event_type or not room_name:
            raise ValueError("LiveKit webhook payload must include id, event, and room.name")

        occurred_at = parse_livekit_timestamp(payload.get("createdAt"))
        claimed = self.deduplicator.claim(
            source=EventSource.LIVEKIT,
            event_id=event_id,
            metadata={"event_type": event_type, "room_name": room_name},
        )
        if not claimed:
            return WebhookResult(
                source=EventSource.LIVEKIT.value,
                event_type=event_type,
                accepted=True,
                duplicated=True,
            )

        participant = payload.get("participant") or {}
        existing = self.session_service.get_call_session(room_name)

        if event_type == "room_started":
            session = self._upsert_room_started(existing=existing, room_name=room_name, occurred_at=occurred_at)
            return WebhookResult(
                source=EventSource.LIVEKIT.value,
                event_type=event_type,
                accepted=True,
                session=session,
            )

        if event_type == "participant_joined" and is_sip_participant(participant):
            session = self._upsert_sip_participant_join(
                existing=existing,
                participant=participant,
                room_name=room_name,
                occurred_at=occurred_at,
            )
            return WebhookResult(
                source=EventSource.LIVEKIT.value,
                event_type=event_type,
                accepted=True,
                session=session,
            )

        if event_type == "participant_connection_aborted":
            session = self._upsert_failed_session(
                existing=existing,
                room_name=room_name,
                occurred_at=occurred_at,
            )
            return WebhookResult(
                source=EventSource.LIVEKIT.value,
                event_type=event_type,
                accepted=True,
                session=session,
            )

        if event_type in {"participant_left", "room_finished"}:
            session = self._upsert_completed_session(
                existing=existing,
                room_name=room_name,
                occurred_at=occurred_at,
                disposition=CallDisposition.CALLER_HANGUP,
            )
            return WebhookResult(
                source=EventSource.LIVEKIT.value,
                event_type=event_type,
                accepted=True,
                session=session,
            )

        return WebhookResult(
            source=EventSource.LIVEKIT.value,
            event_type=event_type,
            accepted=True,
            ignored=True,
            session=existing,
        )

    def handle_twilio_status(self, form_data: Mapping[str, Any]) -> WebhookResult:
        """Process a Twilio voice status callback and update an existing session."""

        call_sid = str(form_data.get("CallSid") or "").strip()
        call_status = str(form_data.get("CallStatus") or "").strip().lower()
        if not call_sid or not call_status:
            raise ValueError("Twilio status callback must include CallSid and CallStatus")

        event_id = build_twilio_event_id(form_data)
        occurred_at = parse_twilio_timestamp(form_data.get("Timestamp"))
        claimed = self.deduplicator.claim(
            source=EventSource.TWILIO,
            event_id=event_id,
            metadata={"call_sid": call_sid, "call_status": call_status},
        )
        if not claimed:
            return WebhookResult(
                source=EventSource.TWILIO.value,
                event_type=call_status,
                accepted=True,
                duplicated=True,
            )

        existing = self.session_service.get_call_session_by_provider_call_id(call_sid)
        if existing is None:
            return WebhookResult(
                source=EventSource.TWILIO.value,
                event_type=call_status,
                accepted=True,
                ignored=True,
            )

        session = self._apply_twilio_status(
            existing=existing,
            form_data=form_data,
            occurred_at=occurred_at,
            call_status=call_status,
        )
        return WebhookResult(
            source=EventSource.TWILIO.value,
            event_type=call_status,
            accepted=True,
            session=session,
        )

    def _upsert_room_started(
        self,
        *,
        existing: CallSessionRecord | None,
        room_name: str,
        occurred_at: datetime,
    ) -> CallSessionRecord:
        if existing is not None:
            return existing

        session = CallSessionRecord(
            provider="twilio",
            room_name=room_name,
            agent_config_id=PENDING_AGENT_CONFIG_ID,
            status=CallSessionStatus.CREATED,
            created_at=occurred_at,
        )
        return self.session_service.upsert_call_session(session)

    def _upsert_sip_participant_join(
        self,
        *,
        existing: CallSessionRecord | None,
        participant: Mapping[str, Any],
        room_name: str,
        occurred_at: datetime,
    ) -> CallSessionRecord:
        context = parse_sip_attributes(
            participant.get("attributes"),
            room_name=room_name,
            participant_identity=participant.get("identity"),
            participant_kind=participant.get("kind"),
        )
        matched_config = (
            self.agent_config_service.get_agent_config_by_did(context.did)
            if context.did is not None
            else None
        )

        agent_config_id = (
            matched_config.config_id
            if matched_config is not None
            else existing.agent_config_id if existing is not None else FALLBACK_AGENT_CONFIG_ID
        )
        if matched_config is None and agent_config_id == PENDING_AGENT_CONFIG_ID:
            agent_config_id = FALLBACK_AGENT_CONFIG_ID

        status = map_livekit_call_status(context.call_status)
        disposition = existing.disposition if existing is not None else None
        if matched_config is None:
            status = CallSessionStatus.FAILED
            disposition = CallDisposition.SETUP_FAILED

        session = CallSessionRecord(
            _id=existing.id if existing is not None else None,
            provider="twilio",
            provider_call_id=context.provider_call_id or (existing.provider_call_id if existing else None),
            room_name=room_name,
            did=context.did or (existing.did if existing else None),
            ani=context.ani or (existing.ani if existing else None),
            agent_config_id=agent_config_id,
            status=status,
            created_at=existing.created_at if existing is not None else occurred_at,
            connected_at=resolve_connected_at(
                existing=existing,
                occurred_at=occurred_at,
                status=status,
            ),
            ended_at=existing.ended_at if existing is not None else None,
            duration_seconds=existing.duration_seconds if existing is not None else None,
            disposition=disposition,
            transfer_target=existing.transfer_target if existing is not None else None,
            recovery_count=existing.recovery_count if existing is not None else 0,
            metrics_summary=existing.metrics_summary if existing is not None else CallMetricsSummary(),
            voice_quality=existing.voice_quality if existing is not None else VoiceQualityMetrics(),
        )
        return self.session_service.upsert_call_session(session)

    def _upsert_failed_session(
        self,
        *,
        existing: CallSessionRecord | None,
        room_name: str,
        occurred_at: datetime,
    ) -> CallSessionRecord:
        session = CallSessionRecord(
            _id=existing.id if existing is not None else None,
            provider="twilio",
            provider_call_id=existing.provider_call_id if existing is not None else None,
            room_name=room_name,
            did=existing.did if existing is not None else None,
            ani=existing.ani if existing is not None else None,
            agent_config_id=existing.agent_config_id if existing is not None else PENDING_AGENT_CONFIG_ID,
            status=CallSessionStatus.FAILED,
            created_at=existing.created_at if existing is not None else occurred_at,
            connected_at=existing.connected_at if existing is not None else None,
            ended_at=occurred_at,
            duration_seconds=existing.duration_seconds if existing is not None else None,
            disposition=existing.disposition or CallDisposition.SETUP_FAILED,
            transfer_target=existing.transfer_target if existing is not None else None,
            recovery_count=existing.recovery_count if existing is not None else 0,
            metrics_summary=existing.metrics_summary if existing is not None else CallMetricsSummary(),
            voice_quality=existing.voice_quality if existing is not None else VoiceQualityMetrics(),
        )
        return self.session_service.upsert_call_session(session)

    def _upsert_completed_session(
        self,
        *,
        existing: CallSessionRecord | None,
        room_name: str,
        occurred_at: datetime,
        disposition: CallDisposition,
    ) -> CallSessionRecord:
        session = CallSessionRecord(
            _id=existing.id if existing is not None else None,
            provider="twilio",
            provider_call_id=existing.provider_call_id if existing is not None else None,
            room_name=room_name,
            did=existing.did if existing is not None else None,
            ani=existing.ani if existing is not None else None,
            agent_config_id=existing.agent_config_id if existing is not None else PENDING_AGENT_CONFIG_ID,
            status=(
                existing.status
                if existing is not None and existing.status == CallSessionStatus.FAILED
                else CallSessionStatus.COMPLETED
            ),
            created_at=existing.created_at if existing is not None else occurred_at,
            connected_at=existing.connected_at if existing is not None else None,
            ended_at=occurred_at,
            duration_seconds=existing.duration_seconds if existing is not None else None,
            disposition=existing.disposition or disposition if existing is not None else disposition,
            transfer_target=existing.transfer_target if existing is not None else None,
            recovery_count=existing.recovery_count if existing is not None else 0,
            metrics_summary=existing.metrics_summary if existing is not None else CallMetricsSummary(),
            voice_quality=existing.voice_quality if existing is not None else VoiceQualityMetrics(),
        )
        return self.session_service.upsert_call_session(session)

    def _apply_twilio_status(
        self,
        *,
        existing: CallSessionRecord,
        form_data: Mapping[str, Any],
        occurred_at: datetime,
        call_status: str,
    ) -> CallSessionRecord:
        mapped_status = map_twilio_status(call_status)
        mapped_disposition = map_twilio_disposition(call_status)

        if existing.status == CallSessionStatus.FAILED and mapped_status == CallSessionStatus.COMPLETED:
            mapped_status = existing.status
        if existing.disposition == CallDisposition.SETUP_FAILED and mapped_disposition == CallDisposition.COMPLETED:
            mapped_disposition = existing.disposition

        did = existing.did or normalize_phone_number(form_data.get("To"))
        ani = existing.ani or normalize_phone_number(form_data.get("From"))
        duration_seconds = existing.duration_seconds
        if form_data.get("CallDuration"):
            duration_seconds = float(form_data["CallDuration"])

        session = CallSessionRecord(
            _id=existing.id,
            provider=existing.provider,
            provider_call_id=existing.provider_call_id or str(form_data.get("CallSid")),
            room_name=existing.room_name,
            did=did,
            ani=ani,
            agent_config_id=existing.agent_config_id,
            status=mapped_status,
            created_at=existing.created_at,
            connected_at=resolve_connected_at(existing=existing, occurred_at=occurred_at, status=mapped_status),
            ended_at=(
                occurred_at
                if mapped_status in {CallSessionStatus.COMPLETED, CallSessionStatus.FAILED}
                else existing.ended_at
            ),
            duration_seconds=duration_seconds,
            disposition=mapped_disposition or existing.disposition,
            transfer_target=existing.transfer_target,
            recovery_count=existing.recovery_count,
            metrics_summary=existing.metrics_summary,
            voice_quality=existing.voice_quality,
        )
        return self.session_service.upsert_call_session(session)


def parse_livekit_timestamp(raw_timestamp: Any) -> datetime:
    """Parse a LiveKit webhook timestamp into UTC."""

    if raw_timestamp is None:
        return datetime.now(UTC)
    if isinstance(raw_timestamp, datetime):
        return raw_timestamp.astimezone(UTC)
    return datetime.fromtimestamp(int(raw_timestamp), UTC)


def parse_twilio_timestamp(raw_timestamp: Any) -> datetime:
    """Parse a Twilio callback timestamp into UTC, with a safe fallback."""

    if raw_timestamp is None:
        return datetime.now(UTC)
    if isinstance(raw_timestamp, datetime):
        return raw_timestamp.astimezone(UTC)
    try:
        parsed = parsedate_to_datetime(str(raw_timestamp))
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


def build_twilio_event_id(form_data: Mapping[str, Any]) -> str:
    """Build a stable idempotency key for a Twilio status callback."""

    parts = {
        "CallSid": form_data.get("CallSid"),
        "CallStatus": form_data.get("CallStatus"),
        "Timestamp": form_data.get("Timestamp"),
        "CallDuration": form_data.get("CallDuration"),
        "From": form_data.get("From"),
        "To": form_data.get("To"),
    }
    digest = hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()
    return f"twilio-status-{digest}"


def map_livekit_call_status(call_status: str | None) -> CallSessionStatus:
    """Map LiveKit SIP call status into a persisted call-session status."""

    if call_status == "active":
        return CallSessionStatus.ACTIVE
    if call_status == "hangup":
        return CallSessionStatus.COMPLETED
    return CallSessionStatus.CREATED


def map_twilio_status(call_status: str) -> CallSessionStatus:
    """Map Twilio call status strings into persisted call-session statuses."""

    if call_status == "in-progress":
        return CallSessionStatus.ACTIVE
    if call_status == "completed":
        return CallSessionStatus.COMPLETED
    if call_status in {"busy", "failed", "no-answer", "canceled"}:
        return CallSessionStatus.FAILED
    return CallSessionStatus.CREATED


def map_twilio_disposition(call_status: str) -> CallDisposition | None:
    """Map Twilio call status into a terminal disposition when applicable."""

    if call_status == "completed":
        return CallDisposition.COMPLETED
    if call_status in {"busy", "failed", "no-answer", "canceled"}:
        return CallDisposition.SETUP_FAILED
    return None


def resolve_connected_at(
    *,
    existing: CallSessionRecord | None,
    occurred_at: datetime,
    status: CallSessionStatus,
) -> datetime | None:
    """Preserve an existing connection time or set it once the call becomes active."""

    if existing is not None and existing.connected_at is not None:
        return existing.connected_at
    if status == CallSessionStatus.ACTIVE:
        return occurred_at
    return None


def normalize_phone_number(value: Any) -> str | None:
    """Return a candidate E.164 phone number or `None` when the value is not usable."""

    if value is None:
        return None
    text = str(value).strip()
    if text.startswith("+"):
        return text
    return None
