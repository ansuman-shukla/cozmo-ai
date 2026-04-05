"""Objection routing and scripted fallback helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence


class ObjectionRoute(str, Enum):
    """Supported routing outcomes for one caller utterance."""

    LLM = "llm"
    SCRIPTED = "scripted"
    TRANSFER = "transfer"


@dataclass(frozen=True, slots=True)
class ObjectionDecision:
    """Normalized outcome of objection and escalation classification."""

    route: ObjectionRoute
    objection_type: str | None = None
    scripted_response: str | None = None


class ObjectionHandler:
    """Map caller objections into scripted, LLM, or transfer branches."""

    TRUST_PATTERNS: tuple[str, ...] = (
        "don't believe",
        "do not believe",
        "not real",
        "is this a scam",
        "sounds like a scam",
        "who are you",
        "why should i trust",
        "not comfortable",
    )
    DEFAULT_TRANSFER_PATTERNS: tuple[str, ...] = (
        "human",
        "person",
        "representative",
        "manager",
        "agent",
        "someone else",
        "transfer me",
    )
    TRUST_RESPONSE = (
        "I understand the concern. I can share grounded details, or I can connect you with a human agent."
    )

    def classify(
        self,
        text: str,
        *,
        escalation_triggers: Sequence[str] = (),
    ) -> ObjectionDecision:
        """Classify one caller utterance into the next routing branch."""

        normalized = " ".join(str(text or "").split()).strip().lower()
        if not normalized:
            return ObjectionDecision(route=ObjectionRoute.LLM)

        transfer_patterns = tuple(
            pattern.lower()
            for pattern in (
                *self.DEFAULT_TRANSFER_PATTERNS,
                *(trigger for trigger in escalation_triggers if str(trigger).strip()),
            )
        )
        if any(pattern in normalized for pattern in transfer_patterns):
            return ObjectionDecision(
                route=ObjectionRoute.TRANSFER,
                objection_type="handoff_request",
            )

        if any(pattern in normalized for pattern in self.TRUST_PATTERNS):
            return ObjectionDecision(
                route=ObjectionRoute.SCRIPTED,
                objection_type="trust",
                scripted_response=self.TRUST_RESPONSE,
            )

        return ObjectionDecision(route=ObjectionRoute.LLM)

    def handle(self, text: str, *, escalation_triggers: Sequence[str] = ()) -> str:
        """Return a scripted response when the utterance maps to one."""

        decision = self.classify(text, escalation_triggers=escalation_triggers)
        return decision.scripted_response or ""
