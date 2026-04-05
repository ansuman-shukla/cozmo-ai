"""Transfer request modeling and response helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cozmo_contracts.runtime import AgentRuntimeConfig


@dataclass(frozen=True, slots=True)
class TransferRequest:
    """Normalized request to escalate the current call to a human target."""

    room_name: str
    agent_config_id: str
    transfer_target: str
    reason: str
    provider_call_id: str | None = None
    did: str | None = None
    ani: str | None = None


@dataclass(frozen=True, slots=True)
class TransferOutcome:
    """Result of attempting a human transfer."""

    success: bool
    transfer_target: str
    message: str


class TransferService(Protocol):
    """Protocol for provider-backed human transfer implementations."""

    async def transfer(self, request: TransferRequest) -> TransferOutcome:
        """Attempt to transfer the active call."""


class TransferRequestBuilder:
    """Build transfer requests from the active runtime and call metadata."""

    def build(
        self,
        *,
        runtime_config: AgentRuntimeConfig,
        room_name: str,
        reason: str,
        provider_call_id: str | None = None,
        did: str | None = None,
        ani: str | None = None,
    ) -> TransferRequest:
        """Build a transfer request for the configured human target."""

        transfer_target = (runtime_config.transfer_target or "").strip()
        if not transfer_target:
            raise ValueError("Transfer target is not configured for this agent")

        return TransferRequest(
            room_name=room_name,
            agent_config_id=runtime_config.config_id,
            transfer_target=transfer_target,
            reason=reason,
            provider_call_id=provider_call_id,
            did=did or runtime_config.did,
            ani=ani,
        )


def build_transfer_success_response(target: str) -> str:
    """Return the spoken response for a successful handoff."""

    normalized = " ".join(str(target or "").split()).strip() or "the team"
    return f"I'll connect you to {normalized} now."
