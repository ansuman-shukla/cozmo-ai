"""LiveKit provisioning helpers for telephony control-plane setup."""

from dataclasses import dataclass
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from cozmo_contracts.validators import NonEmptyText, PhoneNumber

DEFAULT_CALL_ROOM_PREFIX = "call-"
DEFAULT_DISPATCH_RULE_NAME = "cozmo-inbound-dispatch"
DEFAULT_DISPATCH_AGENT_NAME = "inbound-agent"


def prune_empty_values(value: Any) -> Any:
    """Remove empty containers from nested payloads before emitting API JSON."""

    if isinstance(value, dict):
        cleaned = {key: prune_empty_values(item) for key, item in value.items()}
        return {key: item for key, item in cleaned.items() if item not in (None, "", [], {})}
    if isinstance(value, list):
        cleaned = [prune_empty_values(item) for item in value]
        return [item for item in cleaned if item not in (None, "", [], {})]
    return value


class LiveKitInboundTrunkPayload(BaseModel):
    """Validated payload shape for a LiveKit inbound SIP trunk."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: NonEmptyText
    numbers: list[PhoneNumber] = Field(min_length=1)
    metadata: str | None = None
    allowed_addresses: list[NonEmptyText] = Field(default_factory=list, alias="allowedAddresses")
    allowed_numbers: list[PhoneNumber] = Field(default_factory=list, alias="allowedNumbers")
    krisp_enabled: bool = Field(default=True, alias="krispEnabled")


class LiveKitDispatchAgentPayload(BaseModel):
    """Validated agent-dispatch entry embedded in a dispatch rule."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    agent_name: NonEmptyText = Field(alias="agentName")
    metadata: str | None = None


class LiveKitRoomConfigPayload(BaseModel):
    """Room configuration emitted inside a dispatch rule payload."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    agents: list[LiveKitDispatchAgentPayload] = Field(default_factory=list)


class LiveKitDispatchRuleIndividualPayload(BaseModel):
    """Dispatch-rule variant that creates one room per inbound caller."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    room_prefix: NonEmptyText = Field(default=DEFAULT_CALL_ROOM_PREFIX, alias="roomPrefix")


class LiveKitDispatchRuleDefinition(BaseModel):
    """Rule wrapper used by LiveKit's dispatch-rule API."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    dispatch_rule_individual: LiveKitDispatchRuleIndividualPayload = Field(
        alias="dispatchRuleIndividual"
    )


class LiveKitDispatchRulePayload(BaseModel):
    """Validated payload shape for a LiveKit SIP dispatch rule."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: NonEmptyText
    rule: LiveKitDispatchRuleDefinition
    trunk_ids: list[NonEmptyText] = Field(default_factory=list, alias="trunkIds")
    room_config: LiveKitRoomConfigPayload | None = Field(default=None, alias="roomConfig")
    attributes: dict[NonEmptyText, NonEmptyText] = Field(default_factory=dict)
    metadata: str | None = None


@dataclass(slots=True, frozen=True)
class TelephonySetupReport:
    """Validation report for the pre-provisioned SIP control plane."""

    ready: bool
    missing: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(slots=True)
class LiveKitService:
    """Provisioning and validation helpers for LiveKit telephony resources."""

    base_url: str
    sip_trunk_id: str | None = None
    dispatch_rule_name: str = DEFAULT_DISPATCH_RULE_NAME
    dispatch_agent_name: str = DEFAULT_DISPATCH_AGENT_NAME
    room_prefix: str = DEFAULT_CALL_ROOM_PREFIX

    @classmethod
    def from_settings(cls, settings: Any) -> "LiveKitService":
        """Build the service from a backend settings object."""

        return cls(
            base_url=getattr(settings, "livekit_url", ""),
            sip_trunk_id=getattr(settings, "livekit_sip_trunk_id", None),
            dispatch_rule_name=getattr(
                settings,
                "livekit_sip_dispatch_rule_name",
                DEFAULT_DISPATCH_RULE_NAME,
            ),
            dispatch_agent_name=getattr(
                settings,
                "livekit_dispatch_agent_name",
                DEFAULT_DISPATCH_AGENT_NAME,
            ),
            room_prefix=getattr(settings, "call_room_prefix", DEFAULT_CALL_ROOM_PREFIX),
        )

    def health(self) -> dict[str, str]:
        return {"service": "livekit", "base_url": self.base_url}

    def validation_report(self) -> TelephonySetupReport:
        """Validate that the documented pre-provisioned LiveKit pieces exist."""

        missing: list[str] = []
        warnings: list[str] = []

        if not self.base_url:
            missing.append("LIVEKIT_URL")
        if not self.sip_trunk_id:
            missing.append("LIVEKIT_SIP_TRUNK_ID")
        if not self.dispatch_rule_name:
            missing.append("LIVEKIT_SIP_DISPATCH_RULE_NAME")
        if not self.dispatch_agent_name:
            missing.append("LIVEKIT_DISPATCH_AGENT_NAME")
        if not self.room_prefix:
            missing.append("CALL_ROOM_PREFIX")

        if self.base_url and not self.base_url.startswith(("ws://", "wss://", "http://", "https://")):
            warnings.append("LIVEKIT_URL should use a ws://, wss://, http://, or https:// scheme")

        return TelephonySetupReport(
            ready=not missing,
            missing=tuple(missing),
            warnings=tuple(warnings),
        )

    def build_inbound_trunk_payload(
        self,
        *,
        trunk_name: str,
        phone_numbers: list[str],
        allowed_addresses: list[str] | None = None,
        allowed_numbers: list[str] | None = None,
        metadata: str | None = None,
        krisp_enabled: bool = True,
    ) -> dict[str, Any]:
        """Build a validated LiveKit inbound-trunk payload for dashboard or API use."""

        payload = LiveKitInboundTrunkPayload(
            name=trunk_name,
            numbers=phone_numbers,
            metadata=metadata,
            allowedAddresses=allowed_addresses or [],
            allowedNumbers=allowed_numbers or [],
            krispEnabled=krisp_enabled,
        )
        return prune_empty_values(payload.model_dump(by_alias=True, exclude_none=True))

    def build_dispatch_rule_payload(
        self,
        *,
        trunk_ids: list[str] | None = None,
        participant_attributes: Mapping[str, str] | None = None,
        metadata: str | None = None,
        agent_metadata: str | None = None,
    ) -> dict[str, Any]:
        """Build a validated LiveKit dispatch-rule payload with agent dispatch enabled."""

        payload = LiveKitDispatchRulePayload(
            name=self.dispatch_rule_name,
            rule=LiveKitDispatchRuleDefinition(
                dispatchRuleIndividual=LiveKitDispatchRuleIndividualPayload(
                    roomPrefix=self.room_prefix
                )
            ),
            trunkIds=trunk_ids or [],
            roomConfig=LiveKitRoomConfigPayload(
                agents=[
                    LiveKitDispatchAgentPayload(
                        agentName=self.dispatch_agent_name,
                        metadata=agent_metadata,
                    )
                ]
            ),
            attributes=dict(participant_attributes or {}),
            metadata=metadata,
        )
        return prune_empty_values(payload.model_dump(by_alias=True, exclude_none=True))
