"""Shared runtime configuration models."""

from pydantic import Field

from cozmo_contracts.models import AgentConfigRecord, ContractModel
from cozmo_contracts.validators import ConfigId, NonEmptyText, PhoneNumber, TransferTarget


class RetrievalSettings(ContractModel):
    """Retrieval-specific runtime settings."""

    embedding_model: NonEmptyText = "text-embedding-3-small"
    top_k: int = Field(default=3, ge=1, le=10)
    min_score: float = Field(default=0.35, ge=0, le=1)
    no_answer_response: NonEmptyText = (
        "I do not have enough grounded information to answer that confidently."
    )


class TimeoutSettings(ContractModel):
    """Provider timeout configuration in milliseconds."""

    stt_ms: int = Field(default=5000, ge=1)
    llm_ms: int = Field(default=8000, ge=1)
    tts_ms: int = Field(default=5000, ge=1)
    kb_ms: int = Field(default=200, ge=1)


class AgentRuntimeConfig(ContractModel):
    """Per-call runtime snapshot loaded by the worker job."""

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
    max_history_turns: int = Field(default=10, ge=1, le=100)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    timeouts: TimeoutSettings = Field(default_factory=TimeoutSettings)

    @classmethod
    def from_agent_config(
        cls,
        agent_config: AgentConfigRecord,
        *,
        max_history_turns: int = 10,
        retrieval: RetrievalSettings | None = None,
        timeouts: TimeoutSettings | None = None,
    ) -> "AgentRuntimeConfig":
        """Create a runtime snapshot from a stored agent configuration."""

        payload = agent_config.model_dump(
            include={
                "config_id",
                "did",
                "agent_name",
                "persona_prompt",
                "kb_collection",
                "llm_provider",
                "llm_model",
                "tts_provider",
                "tts_model",
                "tts_voice",
                "escalation_triggers",
                "transfer_target",
                "active",
            }
        )
        payload["max_history_turns"] = max_history_turns
        payload["retrieval"] = retrieval or RetrievalSettings()
        payload["timeouts"] = timeouts or TimeoutSettings()
        return cls(**payload)
