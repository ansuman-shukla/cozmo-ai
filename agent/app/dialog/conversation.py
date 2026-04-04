"""Conversation state container."""

from dataclasses import dataclass, field


@dataclass(slots=True)
class ConversationState:
    """Maintain the turn-by-turn conversation transcript in memory."""

    turns: list[str] = field(default_factory=list)

    def append(self, turn: str) -> None:
        self.turns.append(turn)

