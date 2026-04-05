"""Prompt building and LLM adapter helpers."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any, Sequence

from cozmo_contracts.runtime import AgentRuntimeConfig

from app.dialog.conversation import ConversationState
from app.pipeline.rag import RetrievedChunk


class LlmAdapterError(RuntimeError):
    """Raised when the configured LLM provider cannot be initialized."""


@dataclass(frozen=True, slots=True)
class LlmResponse:
    """Normalized LLM output returned by the adapter."""

    text: str
    provider: str
    model: str


class PromptBuilder:
    """Construct provider-ready chat context from runtime state."""

    def build_system_prompt(
        self,
        *,
        runtime_config: AgentRuntimeConfig,
        knowledge_chunks: Sequence[RetrievedChunk],
    ) -> str:
        """Build the grounded system prompt for the current call."""

        lines = [
            f"You are {runtime_config.agent_name}, the voice agent for DID {runtime_config.did}.",
            runtime_config.persona_prompt.strip(),
            f"Use grounded knowledge from the `{runtime_config.kb_collection}` collection when it is relevant.",
            "Keep phone-call answers concise, clear, and action-oriented.",
        ]
        if runtime_config.escalation_triggers:
            lines.append(
                "Escalate when the caller asks for or clearly needs: "
                + ", ".join(runtime_config.escalation_triggers)
                + "."
            )
        if runtime_config.transfer_target:
            lines.append(f"Escalation target: {runtime_config.transfer_target}.")
        if knowledge_chunks:
            lines.append("Grounded knowledge:")
            lines.extend(
                f"- [{chunk.chunk_id}] {chunk.text} (score={chunk.score:.2f})"
                for chunk in knowledge_chunks
            )
        else:
            lines.append("No grounded knowledge was retrieved for this turn.")
        return "\n".join(lines)

    def build_chat_context(
        self,
        *,
        runtime_config: AgentRuntimeConfig,
        conversation: ConversationState,
        pending_user_text: str,
        knowledge_chunks: Sequence[RetrievedChunk],
    ) -> Any:
        """Build a LiveKit chat context for the configured provider adapter."""

        from livekit.agents import llm

        chat_ctx = llm.ChatContext.empty()
        chat_ctx.add_message(
            role="system",
            content=self.build_system_prompt(
                runtime_config=runtime_config,
                knowledge_chunks=knowledge_chunks,
            ),
        )
        for turn in conversation.recent(runtime_config.max_history_turns):
            role = "assistant" if turn.speaker == "agent" else "user"
            if turn.text:
                chat_ctx.add_message(role=role, content=turn.text, interrupted=turn.interrupted)
        if pending_user_text.strip():
            chat_ctx.add_message(role="user", content=pending_user_text.strip())
        return chat_ctx


@dataclass(slots=True)
class LlmAdapter:
    """Thin provider wrapper for Gemini text completion through LiveKit plugins."""

    provider: str
    model: str
    api_key: str | None = None
    temperature: float = 0.2
    max_output_tokens: int = 256

    @classmethod
    def from_settings(cls, settings: Any) -> "LlmAdapter":
        """Build an LLM adapter from the shared worker settings."""

        api_key: str | None = None
        if str(settings.llm_provider) == "gemini":
            api_key = getattr(settings, "gemini_api_key", None)
        elif str(settings.llm_provider) == "openai":
            api_key = getattr(settings, "openai_api_key", None)

        return cls(
            provider=str(settings.llm_provider),
            model=str(settings.llm_model),
            api_key=api_key,
        )

    def create_provider(self) -> Any:
        """Create the configured provider plugin object."""

        if self.provider != "gemini":
            raise LlmAdapterError(f"Unsupported LLM provider: {self.provider}")

        try:
            google = importlib.import_module("livekit.plugins.google")
        except ImportError as exc:
            raise LlmAdapterError(
                "Gemini LiveKit plugin is not installed; run `uv sync --all-packages --dev`."
            ) from exc

        kwargs: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        return google.LLM(**kwargs)

    async def complete(self, chat_ctx: Any) -> LlmResponse:
        """Stream and collect a text completion from the configured provider."""

        client = self.create_provider()
        try:
            chunks: list[str] = []
            async with client.chat(chat_ctx=chat_ctx) as stream:
                async for chunk in stream:
                    delta = getattr(chunk, "delta", None)
                    content = getattr(delta, "content", None) if delta is not None else None
                    if isinstance(content, str):
                        chunks.append(content)
                    elif isinstance(content, list):
                        chunks.extend(part for part in content if isinstance(part, str))
            return LlmResponse(
                text="".join(chunks).strip(),
                provider=self.provider,
                model=self.model,
            )
        finally:
            close = getattr(client, "aclose", None)
            if callable(close):
                await close()
