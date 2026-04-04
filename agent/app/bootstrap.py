"""Bootstrap helpers for resolving per-call runtime context."""

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from pymongo import DESCENDING, MongoClient
from pymongo.collection import Collection

from cozmo_contracts.models import AgentConfigRecord

from app.config import Settings
from app.telephony import parse_sip_attributes


class AgentBootstrapError(RuntimeError):
    """Raised when a dispatched call cannot be bootstrapped safely."""


class AgentConfigLookup(Protocol):
    """Lookup protocol for retrieving an active agent config by DID."""

    def get_by_did(self, did: str) -> AgentConfigRecord | None:
        """Return the active config for the supplied DID, if any."""


@dataclass(slots=True, frozen=True)
class ResolvedCallContext:
    """Typed runtime context resolved once at the start of a call."""

    room_name: str
    did: str
    ani: str | None
    provider_call_id: str | None
    livekit_call_id: str | None
    participant_identity: str | None
    agent_config: AgentConfigRecord

    def participant_attributes(self) -> dict[str, str]:
        """Serialize the resolved context into agent participant attributes."""

        attributes = {
            "cozmo.bootstrap_state": "ready",
            "cozmo.agent_config_id": self.agent_config.config_id,
            "cozmo.did": self.did,
            "cozmo.kb_collection": self.agent_config.kb_collection,
        }
        if self.ani:
            attributes["cozmo.ani"] = self.ani
        if self.provider_call_id:
            attributes["cozmo.provider_call_id"] = self.provider_call_id
        if self.livekit_call_id:
            attributes["cozmo.livekit_call_id"] = self.livekit_call_id
        if self.participant_identity:
            attributes["cozmo.participant_identity"] = self.participant_identity
        return attributes

    def participant_metadata(self) -> dict[str, str]:
        """Return compact JSON metadata fields for observability."""

        metadata = {
            "room_name": self.room_name,
            "agent_config_id": self.agent_config.config_id,
            "did": self.did,
        }
        if self.provider_call_id:
            metadata["provider_call_id"] = self.provider_call_id
        return metadata


@dataclass(slots=True)
class MongoAgentConfigRepository:
    """Read-only Mongo lookup wrapper for active agent configs."""

    collection: Collection[Any]

    def get_by_did(self, did: str) -> AgentConfigRecord | None:
        """Load the newest active config for a DID."""

        document = self.collection.find_one(
            {"did": did, "active": True},
            sort=[("updated_at", DESCENDING)],
        )
        if document is None:
            return None
        return AgentConfigRecord.model_validate(document)


@dataclass(slots=True)
class MongoAgentConfigStore:
    """Lifecycle wrapper around the Mongo client used for bootstrap lookups."""

    client: MongoClient[Any]
    repository: MongoAgentConfigRepository

    @classmethod
    def from_settings(cls, settings: Settings) -> "MongoAgentConfigStore":
        """Create a store from the shared agent settings."""

        client: MongoClient[Any] = MongoClient(settings.mongo_uri)
        database_name = settings.mongo_database or "cozmo"
        repository = MongoAgentConfigRepository(client[database_name]["agent_configs"])
        return cls(client=client, repository=repository)

    def close(self) -> None:
        """Close the Mongo client when the worker stops."""

        self.client.close()


def room_name_matches_prefix(room_name: str, prefix: str) -> bool:
    """Return whether the room belongs to the configured inbound dispatch prefix."""

    return bool(room_name) and bool(prefix) and room_name.startswith(prefix)


def build_agent_identity(worker_name: str, room_name: str) -> str:
    """Build a stable, room-derived agent participant identity."""

    normalized = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in room_name.lower()
    ).strip("-")
    suffix = normalized[:32] or "session"
    return f"{worker_name}-{suffix}"[:96]


def resolve_call_context(
    *,
    repository: AgentConfigLookup,
    room_name: str,
    participant_attributes: Mapping[str, str] | None,
    participant_identity: str | None = None,
    participant_kind: str | int | None = None,
) -> ResolvedCallContext:
    """Resolve the agent runtime context from the SIP participant and Mongo config."""

    sip_context = parse_sip_attributes(
        participant_attributes,
        room_name=room_name,
        participant_identity=participant_identity,
        participant_kind=participant_kind,
    )
    if not sip_context.did:
        raise AgentBootstrapError("Inbound SIP participant is missing sip.trunkPhoneNumber")

    agent_config = repository.get_by_did(sip_context.did)
    if agent_config is None:
        raise AgentBootstrapError(f"No active agent config for DID {sip_context.did}")

    return ResolvedCallContext(
        room_name=room_name,
        did=sip_context.did,
        ani=sip_context.ani,
        provider_call_id=sip_context.provider_call_id,
        livekit_call_id=sip_context.livekit_call_id,
        participant_identity=sip_context.participant_identity,
        agent_config=agent_config,
    )
