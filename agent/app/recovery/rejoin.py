"""Worker crash recovery and replacement-job planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, Sequence

from pymongo import DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from cozmo_contracts.models import TranscriptTurn


class RecoveryLeaseSink(Protocol):
    """Protocol for one-time room recovery claims."""

    def claim_recovery(self, room_name: str) -> bool:
        """Claim the room for recovery if it has not already been claimed."""


class TranscriptHistorySource(Protocol):
    """Protocol for transcript history reload during recovery."""

    def list_by_room_name(self, room_name: str) -> list[TranscriptTurn]:
        """Return transcript history for the room in turn order."""


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    """Replacement-job recovery plan for a crashed room."""

    room_name: str
    should_dispatch_replacement: bool
    recovery_prompt: str | None = None
    history_turns: tuple[TranscriptTurn, ...] = ()


@dataclass(slots=True)
class MongoRecoveryLeaseRepository:
    """Mongo-backed room recovery markers."""

    collection: Collection[Any]

    def claim_recovery(self, room_name: str) -> bool:
        """Claim recovery for a room exactly once."""

        try:
            self.collection.insert_one(
                {
                    "room_name": room_name,
                    "claimed_at": datetime.now(UTC),
                    "state": "recoverable",
                }
            )
        except DuplicateKeyError:
            return False
        return True


@dataclass(slots=True)
class MongoRecoveryStore:
    """Lifecycle wrapper for recovery markers."""

    client: MongoClient[Any]
    repository: MongoRecoveryLeaseRepository

    @classmethod
    def from_connection(
        cls,
        *,
        client: MongoClient[Any],
        database_name: str,
    ) -> "MongoRecoveryStore":
        """Create a recovery marker store from an existing Mongo client."""

        repository = MongoRecoveryLeaseRepository(client[database_name]["recovery_markers"])
        return cls(client=client, repository=repository)


@dataclass(slots=True)
class RejoinCoordinator:
    """Plan one replacement attempt after a recoverable job failure."""

    lease_sink: RecoveryLeaseSink
    transcript_source: TranscriptHistorySource
    max_history_turns: int = 4

    def plan_replacement(self, room_name: str) -> RecoveryPlan:
        """Claim recovery once and build the replacement-job prompt."""

        claimed = self.lease_sink.claim_recovery(room_name)
        if not claimed:
            return RecoveryPlan(
                room_name=room_name,
                should_dispatch_replacement=False,
            )

        history = tuple(self.transcript_source.list_by_room_name(room_name)[-self.max_history_turns :])
        prompt = self.build_recovery_prompt(history)
        return RecoveryPlan(
            room_name=room_name,
            should_dispatch_replacement=True,
            recovery_prompt=prompt,
            history_turns=history,
        )

    def build_recovery_prompt(self, history_turns: Sequence[TranscriptTurn]) -> str | None:
        """Build a short resume prompt from the latest transcript turns."""

        if not history_turns:
            return "The previous agent session ended unexpectedly. Rejoin briefly, apologize for the interruption, and continue helping the caller."

        lines = [
            "The previous agent session ended unexpectedly. Rejoin the room, apologize briefly, and continue from this context:",
        ]
        for turn in history_turns:
            speaker = "Caller" if turn.speaker.value == "user" else "Agent"
            suffix = " [interrupted]" if turn.interrupted else ""
            lines.append(f"- {speaker}: {turn.text}{suffix}")
        return "\n".join(lines)
