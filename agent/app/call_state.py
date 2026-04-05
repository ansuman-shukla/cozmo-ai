"""Call-session state update helpers used by the worker."""

from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import dataclass
from typing import Any, Protocol

from pymongo import MongoClient
from pymongo.collection import Collection

from cozmo_contracts.models import CallDisposition, CallSessionStatus, VoiceQualityMetrics


class CallStateSink(Protocol):
    """Protocol for updating call-session transfer state from the worker."""

    def mark_active(self, room_name: str, connected_at: datetime | None = None) -> Any:
        """Mark the call as active once the worker has joined and bootstrapped it."""

    def mark_transferred(self, room_name: str, transfer_target: str) -> Any:
        """Mark the active call as transferred to the supplied target."""

    def mark_recovery_pending(self, room_name: str) -> Any:
        """Increment the room recovery counter after a recoverable crash."""

    def update_voice_quality(self, room_name: str, quality: VoiceQualityMetrics) -> Any:
        """Persist the latest aggregated room-quality snapshot for the room."""

    def update_call_setup_metrics(self, room_name: str, call_setup_ms: float) -> Any:
        """Persist the call setup timing summary for the room."""


@dataclass(slots=True)
class MongoCallStateRepository:
    """Mongo-backed call-session state updates."""

    collection: Collection[Any]

    def mark_active(self, room_name: str, connected_at: datetime | None = None) -> Any:
        """Persist an active call status for a room once media bootstrap succeeds."""

        existing = self.collection.find_one({"room_name": room_name}, {"connected_at": 1})
        effective_connected_at = None
        if existing is not None:
            effective_connected_at = existing.get("connected_at")
        if effective_connected_at is None:
            effective_connected_at = connected_at or datetime.now(UTC)

        self.collection.update_one(
            {"room_name": room_name},
            {
                "$set": {
                    "status": CallSessionStatus.ACTIVE.value,
                    "connected_at": effective_connected_at,
                }
            },
        )
        return self.collection.find_one({"room_name": room_name})

    def mark_transferred(self, room_name: str, transfer_target: str) -> Any:
        """Mark the room as transferred and persist the transfer target."""

        self.collection.update_one(
            {"room_name": room_name},
            {
                "$set": {
                    "status": CallSessionStatus.TRANSFERRED.value,
                    "disposition": CallDisposition.TRANSFERRED.value,
                    "transfer_target": transfer_target,
                }
            },
        )
        return self.collection.find_one({"room_name": room_name})

    def mark_recovery_pending(self, room_name: str) -> Any:
        """Increment recovery count for a room after a recoverable failure."""

        self.collection.update_one(
            {"room_name": room_name},
            {"$inc": {"recovery_count": 1}},
        )
        return self.collection.find_one({"room_name": room_name})

    def update_voice_quality(self, room_name: str, quality: VoiceQualityMetrics) -> Any:
        """Persist the latest aggregated room-quality snapshot for a room."""

        self.collection.update_one(
            {"room_name": room_name},
            {
                "$set": {
                    "voice_quality.avg_jitter_ms": quality.avg_jitter_ms,
                    "voice_quality.packet_loss_pct": quality.packet_loss_pct,
                    "voice_quality.mos_estimate": quality.mos_estimate,
                }
            },
        )
        return self.collection.find_one({"room_name": room_name})

    def update_call_setup_metrics(self, room_name: str, call_setup_ms: float) -> Any:
        """Persist the call setup timing summary for a room."""

        self.collection.update_one(
            {"room_name": room_name},
            {"$set": {"metrics_summary.call_setup_ms": call_setup_ms}},
        )
        return self.collection.find_one({"room_name": room_name})


@dataclass(slots=True)
class MongoCallStateStore:
    """Lifecycle wrapper for worker-side call-session state updates."""

    client: MongoClient[Any]
    repository: MongoCallStateRepository

    @classmethod
    def from_connection(
        cls,
        *,
        client: MongoClient[Any],
        database_name: str,
    ) -> "MongoCallStateStore":
        """Create a call-state store from an existing Mongo client."""

        repository = MongoCallStateRepository(client[database_name]["call_sessions"])
        return cls(client=client, repository=repository)
