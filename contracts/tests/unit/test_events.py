from datetime import UTC, datetime
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError


CONTRACTS_ROOT = Path(__file__).resolve().parents[2]
if str(CONTRACTS_ROOT) not in sys.path:
    sys.path.insert(0, str(CONTRACTS_ROOT))

from cozmo_contracts.events import CallEventPayload, EventSource  # noqa: E402


@pytest.mark.unit
def test_call_event_payload_accepts_valid_marker() -> None:
    event = CallEventPayload(
        event_id="evt-livekit-001",
        source=EventSource.LIVEKIT,
        event_type="participant_joined",
        room_name="call-12345",
        occurred_at=datetime.now(UTC),
        provider_call_id="CA123456789",
        did="+15551234567",
        agent_config_id="sales-main",
        latency_ms=132.5,
        metadata={"participant_identity": "sip-caller-1"},
    )

    assert event.source is EventSource.LIVEKIT
    assert event.metadata["participant_identity"] == "sip-caller-1"


@pytest.mark.unit
def test_call_event_payload_accepts_livekit_phone_room_name() -> None:
    event = CallEventPayload(
        event_id="evt-livekit-003",
        source=EventSource.LIVEKIT,
        event_type="room_started",
        room_name="call-+16625640501-a1b2c3",
        occurred_at=datetime.now(UTC),
    )

    assert event.room_name == "call-+16625640501-a1b2c3"


@pytest.mark.unit
def test_call_event_payload_rejects_negative_latency() -> None:
    with pytest.raises(ValidationError):
        CallEventPayload(
            event_id="evt-livekit-002",
            source=EventSource.TWILIO,
            event_type="call_completed",
            room_name="call-12345",
            occurred_at=datetime.now(UTC),
            latency_ms=-1.0,
        )
