"""Transcript persistence helpers for the worker."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol, Sequence

from pymongo import DESCENDING, MongoClient
from pymongo.collection import Collection

from cozmo_contracts.models import (
    KnowledgeChunkReference,
    TranscriptTurn,
    TurnLatencyMetrics,
    TurnSpeaker,
)

from app.pipeline.rag import RetrievedChunk


class TranscriptSink(Protocol):
    """Protocol for transcript persistence hooks."""

    def append_transcript_turn(self, turn: TranscriptTurn) -> TranscriptTurn:
        """Persist a transcript turn."""

    def next_turn_index(self, room_name: str) -> int:
        """Return the next turn index for a room."""

    def mark_transcript_turn_interrupted(self, room_name: str, turn_index: int) -> TranscriptTurn | None:
        """Mark an existing turn as interrupted."""


class DeadLetterReason(str, Enum):
    """Failure reasons persisted into the transcript dead-letter queue."""

    WRITE_FAILURE = "write_failure"


@dataclass(frozen=True, slots=True)
class TranscriptDeadLetterEntry:
    """Replayable transcript write that could not be persisted live."""

    room_name: str
    turn_index: int
    speaker: str
    text: str
    attempts: int
    error_message: str
    reason: DeadLetterReason = DeadLetterReason.WRITE_FAILURE
    idempotency_key: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = field(default_factory=dict)


class DeadLetterSink(Protocol):
    """Protocol for transcript dead-letter persistence."""

    def enqueue_failed_turn(self, entry: TranscriptDeadLetterEntry) -> TranscriptDeadLetterEntry:
        """Persist a failed transcript write for later replay."""


def _dump_model(document: Any) -> dict[str, Any]:
    payload = document.model_dump(by_alias=True, mode="python", exclude_none=True)
    payload.pop("_id", None)
    return payload


@dataclass(slots=True)
class MongoTranscriptRepository:
    """Mongo-backed transcript repository used by the worker."""

    collection: Collection[Any]

    def append_transcript_turn(self, turn: TranscriptTurn) -> TranscriptTurn:
        payload = _dump_model(turn)
        self.collection.insert_one(payload)
        stored = self.collection.find_one(
            {"room_name": turn.room_name, "turn_index": turn.turn_index}
        )
        return TranscriptTurn.model_validate(stored or payload)

    def next_turn_index(self, room_name: str) -> int:
        document = self.collection.find_one(
            {"room_name": room_name},
            sort=[("turn_index", DESCENDING)],
        )
        if document is None:
            return 0
        return int(document.get("turn_index", -1)) + 1

    def mark_transcript_turn_interrupted(self, room_name: str, turn_index: int) -> TranscriptTurn | None:
        """Mark an existing transcript turn as interrupted."""

        self.collection.update_one(
            {"room_name": room_name, "turn_index": turn_index},
            {"$set": {"interrupted": True}},
        )
        stored = self.collection.find_one(
            {"room_name": room_name, "turn_index": turn_index}
        )
        if stored is None:
            return None
        return TranscriptTurn.model_validate(stored)

    def list_by_room_name(self, room_name: str) -> list[TranscriptTurn]:
        """Return transcript history for recovery or replay flows."""

        documents = self.collection.find({"room_name": room_name})
        if hasattr(documents, "sort"):
            documents = documents.sort("turn_index", DESCENDING)
            documents = list(documents)
            documents.reverse()
        else:
            documents = sorted(list(documents), key=lambda item: item["turn_index"])
        return [TranscriptTurn.model_validate(document) for document in documents]


@dataclass(slots=True)
class MongoTranscriptStore:
    """Lifecycle wrapper for worker transcript persistence."""

    client: MongoClient[Any]
    repository: MongoTranscriptRepository

    @classmethod
    def from_connection(
        cls,
        *,
        client: MongoClient[Any],
        database_name: str,
    ) -> "MongoTranscriptStore":
        """Create a transcript store from an existing Mongo client."""

        repository = MongoTranscriptRepository(client[database_name]["transcripts"])
        return cls(client=client, repository=repository)


@dataclass(slots=True)
class MongoTranscriptDeadLetterRepository:
    """Mongo-backed dead-letter queue for transcript writes."""

    collection: Collection[Any]

    def enqueue_failed_turn(self, entry: TranscriptDeadLetterEntry) -> TranscriptDeadLetterEntry:
        """Persist a failed transcript write for later replay."""

        payload = {
            "room_name": entry.room_name,
            "turn_index": entry.turn_index,
            "speaker": entry.speaker,
            "text": entry.text,
            "attempts": entry.attempts,
            "error_message": entry.error_message,
            "reason": entry.reason.value,
            "idempotency_key": entry.idempotency_key,
            "created_at": entry.created_at,
            "payload": entry.payload,
        }
        self.collection.insert_one(payload)
        return entry


@dataclass(slots=True)
class MongoTranscriptDeadLetterStore:
    """Lifecycle wrapper for transcript dead-letter persistence."""

    client: MongoClient[Any]
    repository: MongoTranscriptDeadLetterRepository

    @classmethod
    def from_connection(
        cls,
        *,
        client: MongoClient[Any],
        database_name: str,
    ) -> "MongoTranscriptDeadLetterStore":
        """Create a transcript dead-letter store from an existing Mongo client."""

        repository = MongoTranscriptDeadLetterRepository(client[database_name]["dlq_transcripts"])
        return cls(client=client, repository=repository)


@dataclass(slots=True)
class TranscriptRecorder:
    """Per-call ordered transcript recorder."""

    room_name: str
    sink: TranscriptSink
    max_retries: int = 1
    dead_letter_sink: DeadLetterSink | None = None
    _next_turn_index: int = field(default=0)
    _last_agent_turn_index: int | None = field(default=None)
    _idempotent_results: dict[str, TranscriptTurn] = field(default_factory=dict)

    @classmethod
    def from_sink(
        cls,
        *,
        room_name: str,
        sink: TranscriptSink,
        max_retries: int = 1,
        dead_letter_sink: DeadLetterSink | None = None,
    ) -> "TranscriptRecorder":
        """Create a recorder and initialize its next turn index from persistence."""

        return cls(
            room_name=room_name,
            sink=sink,
            max_retries=max_retries,
            dead_letter_sink=dead_letter_sink,
            _next_turn_index=sink.next_turn_index(room_name),
        )

    def record_turn(
        self,
        *,
        speaker: TurnSpeaker | str,
        text: str,
        timestamp: datetime | None = None,
        interrupted: bool = False,
        objection_type: str | None = None,
        latency: TurnLatencyMetrics | None = None,
        kb_chunks_used: Sequence[RetrievedChunk] | None = None,
        idempotency_key: str | None = None,
    ) -> TranscriptTurn:
        """Persist a normalized transcript turn and advance the local turn index."""

        if idempotency_key and idempotency_key in self._idempotent_results:
            return self._idempotent_results[idempotency_key]

        normalized_text = " ".join(str(text or "").split()).strip()
        if not normalized_text:
            raise ValueError("Transcript text must be non-empty")

        turn = TranscriptTurn(
            room_name=self.room_name,
            turn_index=self._next_turn_index,
            speaker=TurnSpeaker(speaker.value if isinstance(speaker, TurnSpeaker) else str(speaker)),
            text=normalized_text,
            timestamp=timestamp or datetime.now(UTC),
            interrupted=interrupted,
            objection_type=objection_type,
            latency=latency or TurnLatencyMetrics(),
            kb_chunks_used=[
                KnowledgeChunkReference(chunk_id=chunk.chunk_id, score=chunk.score)
                for chunk in (kb_chunks_used or [])
            ],
        )
        last_error: Exception | None = None
        stored: TranscriptTurn | None = None

        for _attempt in range(self.max_retries + 1):
            try:
                stored = self.sink.append_transcript_turn(turn)
                break
            except Exception as exc:  # pragma: no cover - exact exception depends on persistence layer
                last_error = exc

        if stored is None:
            if self.dead_letter_sink is None:
                raise last_error or RuntimeError("Transcript write failed without an error")
            self.dead_letter_sink.enqueue_failed_turn(
                TranscriptDeadLetterEntry(
                    room_name=turn.room_name,
                    turn_index=turn.turn_index,
                    speaker=turn.speaker.value,
                    text=turn.text,
                    attempts=self.max_retries + 1,
                    error_message=str(last_error or "unknown transcript write failure"),
                    idempotency_key=idempotency_key,
                    payload=_dump_model(turn),
                )
            )
            stored = turn

        if turn.speaker == TurnSpeaker.AGENT:
            self._last_agent_turn_index = turn.turn_index
        self._next_turn_index += 1
        if idempotency_key:
            self._idempotent_results[idempotency_key] = stored
        return stored

    def record_user_turn(self, text: str, **kwargs: Any) -> TranscriptTurn:
        """Persist a caller transcript turn."""

        return self.record_turn(speaker=TurnSpeaker.USER, text=text, **kwargs)

    def record_agent_turn(self, text: str, **kwargs: Any) -> TranscriptTurn:
        """Persist an agent transcript turn."""

        return self.record_turn(speaker=TurnSpeaker.AGENT, text=text, **kwargs)

    def mark_turn_interrupted(self, turn_index: int) -> TranscriptTurn | None:
        """Mark an already-persisted turn as interrupted."""

        return self.sink.mark_transcript_turn_interrupted(self.room_name, turn_index)

    def mark_last_agent_turn_interrupted(self) -> TranscriptTurn | None:
        """Mark the newest persisted agent turn as interrupted, if one exists."""

        if self._last_agent_turn_index is None:
            return None
        return self.mark_turn_interrupted(self._last_agent_turn_index)
