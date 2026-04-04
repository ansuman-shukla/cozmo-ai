"""Session management helpers."""

from dataclasses import dataclass

from cozmo_contracts.models import CallSessionRecord, TranscriptTurn

from app.services.mongo import CallSessionRepository, TranscriptRepository


@dataclass(slots=True)
class SessionService:
    """Service facade for call-session and transcript persistence."""

    call_sessions: CallSessionRepository
    transcripts: TranscriptRepository

    def ensure_indexes(self) -> dict[str, list[str]]:
        """Create the required call-session and transcript indexes."""

        return {
            "call_sessions": self.call_sessions.ensure_indexes(),
            "transcripts": self.transcripts.ensure_indexes(),
        }

    def upsert_call_session(self, record: CallSessionRecord) -> CallSessionRecord:
        """Persist or update a call-session document."""

        return self.call_sessions.upsert(record)

    def get_call_session(self, room_name: str) -> CallSessionRecord | None:
        """Fetch a call-session document by room name."""

        return self.call_sessions.get_by_room_name(room_name)

    def get_call_session_by_provider_call_id(self, provider_call_id: str) -> CallSessionRecord | None:
        """Fetch a call-session document by provider call identifier."""

        return self.call_sessions.get_by_provider_call_id(provider_call_id)

    def list_call_sessions(
        self,
        *,
        status: str | None = None,
        did: str | None = None,
    ) -> list[CallSessionRecord]:
        """Return call sessions filtered by supported query fields."""

        return self.call_sessions.list(status=status, did=did)

    def append_transcript_turn(self, turn: TranscriptTurn) -> TranscriptTurn:
        """Persist a transcript turn."""

        return self.transcripts.insert(turn)

    def list_transcript(self, room_name: str) -> list[TranscriptTurn]:
        """Return the transcript turns for a room in turn order."""

        return self.transcripts.list_by_room_name(room_name)
