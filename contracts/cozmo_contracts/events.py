"""Shared event payload contracts."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from cozmo_contracts.models import ContractModel
from cozmo_contracts.validators import ConfigId, NonEmptyText, PhoneNumber, ProviderCallId, RoomName


class EventSource(str, Enum):
    """Sources that can emit call lifecycle events."""

    LIVEKIT = "livekit"
    TWILIO = "twilio"


class CallEventPayload(ContractModel):
    """Normalized event envelope for webhook-driven lifecycle updates."""

    event_id: NonEmptyText
    source: EventSource
    event_type: NonEmptyText
    room_name: RoomName
    occurred_at: datetime
    provider_call_id: ProviderCallId | None = None
    did: PhoneNumber | None = None
    agent_config_id: ConfigId | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

