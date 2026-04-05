"""Conversation-state helpers used by the per-call worker."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """A single in-memory conversational turn."""

    speaker: str
    text: str
    interrupted: bool = False


@dataclass(slots=True)
class ConversationState:
    """Maintain the turn-by-turn conversation transcript in memory."""

    turns: list[ConversationTurn] = field(default_factory=list)

    def append(self, speaker: str, text: str, *, interrupted: bool = False) -> ConversationTurn:
        """Append a normalized turn to the in-memory transcript."""

        normalized_text = " ".join(str(text).split()).strip()
        turn = ConversationTurn(
            speaker=str(speaker).strip().lower(),
            text=normalized_text,
            interrupted=interrupted,
        )
        self.turns.append(turn)
        return turn

    def recent(self, max_turns: int) -> list[ConversationTurn]:
        """Return the newest N turns for prompt construction."""

        if max_turns <= 0:
            return []
        return self.turns[-max_turns:]
