"""Shared persistence and API-facing contract models."""

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cozmo_contracts.validators import (
    ConfigId,
    NonEmptyText,
    PhoneNumber,
    ProviderCallId,
    RoomName,
    TransferTarget,
)


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


class ContractModel(BaseModel):
    """Base model with strict validation for shared contracts."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CallProvider(str, Enum):
    """Telephony providers supported by the platform."""

    TWILIO = "twilio"


class CallSessionStatus(str, Enum):
    """Lifecycle states for a persisted call session."""

    CREATED = "created"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    RECOVERED = "recovered"
    TRANSFERRED = "transferred"


class CallDisposition(str, Enum):
    """Terminal call dispositions persisted for reporting."""

    COMPLETED = "completed"
    CALLER_HANGUP = "caller_hangup"
    AGENT_ERROR = "agent_error"
    TRANSFERRED = "transferred"
    SETUP_FAILED = "setup_failed"


class TurnSpeaker(str, Enum):
    """Allowed speakers in the transcript store."""

    USER = "user"
    AGENT = "agent"


class CallMetricsSummary(ContractModel):
    """Aggregated latency figures for a completed or active call."""

    avg_perceived_rtt_ms: float | None = Field(default=None, ge=0)
    p95_perceived_rtt_ms: float | None = Field(default=None, ge=0)
    avg_pipeline_rtt_ms: float | None = Field(default=None, ge=0)
    avg_stt_ms: float | None = Field(default=None, ge=0)
    avg_llm_ttft_ms: float | None = Field(default=None, ge=0)
    avg_tts_first_audio_ms: float | None = Field(default=None, ge=0)
    call_setup_ms: float | None = Field(default=None, ge=0)


class VoiceQualityMetrics(ContractModel):
    """Aggregated media-quality metrics for a call."""

    avg_jitter_ms: float | None = Field(default=None, ge=0)
    packet_loss_pct: float | None = Field(default=None, ge=0, le=100)
    mos_estimate: float | None = Field(default=None, ge=1, le=5)


class TurnLatencyMetrics(ContractModel):
    """Per-turn latency breakdown persisted with transcript turns."""

    endpoint_ms: float | None = Field(default=None, ge=0)
    stt_ms: float | None = Field(default=None, ge=0)
    llm_ttft_ms: float | None = Field(default=None, ge=0)
    tts_first_audio_ms: float | None = Field(default=None, ge=0)
    pipeline_rtt_ms: float | None = Field(default=None, ge=0)
    perceived_rtt_ms: float | None = Field(default=None, ge=0)


class KnowledgeChunkReference(ContractModel):
    """A knowledge-base chunk used during answer generation."""

    chunk_id: NonEmptyText
    score: float = Field(ge=0, le=1)


class CallSessionRecord(ContractModel):
    """Persisted lifecycle summary for a single inbound call."""

    id: str | None = Field(default=None, alias="_id")
    provider: CallProvider = CallProvider.TWILIO
    provider_call_id: ProviderCallId | None = None
    room_name: RoomName
    did: PhoneNumber | None = None
    ani: PhoneNumber | None = None
    agent_config_id: ConfigId
    status: CallSessionStatus
    created_at: datetime
    connected_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    disposition: CallDisposition | None = None
    transfer_target: TransferTarget | None = None
    recovery_count: int = Field(default=0, ge=0)
    metrics_summary: CallMetricsSummary = Field(default_factory=CallMetricsSummary)
    voice_quality: VoiceQualityMetrics = Field(default_factory=VoiceQualityMetrics)

    @field_validator("id", mode="before")
    @classmethod
    def normalize_object_id(cls, value: object | None) -> str | None:
        """Coerce MongoDB ObjectId values into strings for API-facing models."""

        if value is None:
            return None
        return str(value)


class TranscriptTurn(ContractModel):
    """Persisted transcript entry for a user or agent turn."""

    id: str | None = Field(default=None, alias="_id")
    room_name: RoomName
    turn_index: int = Field(ge=0)
    speaker: TurnSpeaker
    text: str
    timestamp: datetime
    interrupted: bool = False
    objection_type: str | None = None
    latency: TurnLatencyMetrics = Field(default_factory=TurnLatencyMetrics)
    kb_chunks_used: list[KnowledgeChunkReference] = Field(default_factory=list)

    @field_validator("id", mode="before")
    @classmethod
    def normalize_object_id(cls, value: object | None) -> str | None:
        """Coerce MongoDB ObjectId values into strings for API-facing models."""

        if value is None:
            return None
        return str(value)


class AgentConfigRecord(ContractModel):
    """Persisted agent configuration bound to a DID or SIP path."""

    id: str | None = Field(default=None, alias="_id")
    config_id: ConfigId
    did: PhoneNumber
    agent_name: NonEmptyText
    persona_prompt: NonEmptyText
    kb_collection: NonEmptyText
    llm_provider: NonEmptyText
    llm_model: NonEmptyText
    tts_provider: NonEmptyText
    tts_model: NonEmptyText
    tts_voice: NonEmptyText
    escalation_triggers: list[NonEmptyText] = Field(default_factory=list)
    transfer_target: TransferTarget | None = None
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("id", mode="before")
    @classmethod
    def normalize_object_id(cls, value: object | None) -> str | None:
        """Coerce MongoDB ObjectId values into strings for API-facing models."""

        if value is None:
            return None
        return str(value)
