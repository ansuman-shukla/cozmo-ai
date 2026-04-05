"""Fallback helpers for retrieval misses and transfer failures."""

from __future__ import annotations

from typing import Sequence

from cozmo_contracts.runtime import AgentRuntimeConfig

from app.pipeline.rag import RetrievedChunk


def should_use_no_answer_fallback(knowledge_chunks: Sequence[RetrievedChunk]) -> bool:
    """Return whether the turn should use the configured no-answer path."""

    return len(knowledge_chunks) == 0


def build_no_answer_response(runtime_config: AgentRuntimeConfig) -> str:
    """Return the configured grounded no-answer response for the active runtime."""

    return runtime_config.retrieval.no_answer_response


def build_transfer_failure_response() -> str:
    """Return the fallback response when human transfer cannot be completed."""

    return "I couldn't complete the transfer right now, but I can keep helping here or take a message for the team."
