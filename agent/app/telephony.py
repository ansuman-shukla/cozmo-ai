"""Telephony helpers for SIP participant metadata."""

from dataclasses import dataclass
from typing import Mapping


@dataclass(slots=True)
class SipParticipantContext:
    """Normalized SIP participant metadata for an inbound call."""

    room_name: str
    did: str | None
    ani: str | None
    provider_call_id: str | None
    livekit_call_id: str | None
    call_status: str | None
    participant_identity: str | None
    participant_kind: str | int | None
    attributes: dict[str, str]


def parse_sip_attributes(
    attributes: Mapping[str, str] | None,
    *,
    room_name: str,
    participant_identity: str | None = None,
    participant_kind: str | int | None = None,
) -> SipParticipantContext:
    """Normalize SIP participant attributes into a typed context."""

    normalized_attributes = dict(attributes or {})
    return SipParticipantContext(
        room_name=room_name,
        did=normalized_attributes.get("sip.trunkPhoneNumber"),
        ani=normalized_attributes.get("sip.phoneNumber"),
        provider_call_id=(
            normalized_attributes.get("sip.twilio.callSid")
            or normalized_attributes.get("sip.callIDFull")
            or normalized_attributes.get("sip.callID")
        ),
        livekit_call_id=normalized_attributes.get("sip.callID"),
        call_status=normalized_attributes.get("sip.callStatus"),
        participant_identity=participant_identity,
        participant_kind=participant_kind,
        attributes=normalized_attributes,
    )
