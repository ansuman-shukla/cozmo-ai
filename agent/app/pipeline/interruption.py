"""Interruption coordination for active agent audio playback."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class InterruptionEvent:
    """Snapshot describing a response interruption."""

    reason: str
    dropped_output_count: int


class InterruptionCoordinator:
    """Track active agent playback and cancel queued output on caller speech."""

    def __init__(self) -> None:
        self.reset()

    @property
    def interrupted(self) -> bool:
        """Return whether the active response has been interrupted."""

        return self._interrupted

    @property
    def response_active(self) -> bool:
        """Return whether the coordinator is currently managing a response."""

        return self._response_active

    @property
    def interruption_reason(self) -> str | None:
        """Return the last interruption reason, if any."""

        return self._interruption_reason

    @property
    def queued_output_count(self) -> int:
        """Return the number of queued audio chunks not yet emitted."""

        return len(self._queued_output)

    def begin_response(self) -> None:
        """Begin managing a new agent response."""

        self.reset()
        self._response_active = True

    def enqueue_output(self, chunk: Any) -> bool:
        """Queue one output chunk if the response has not been interrupted."""

        if not self._response_active or self._interrupted:
            return False
        self._queued_output.append(chunk)
        return True

    def dequeue_output(self) -> Any | None:
        """Return the next queued chunk, or `None` once playback should stop."""

        if self._interrupted:
            self._queued_output.clear()
            return None
        if not self._queued_output:
            return None
        return self._queued_output.popleft()

    def interrupt(self, reason: str = "caller_speech") -> InterruptionEvent:
        """Interrupt the active response and drop any queued output."""

        if not self._response_active:
            return InterruptionEvent(reason=reason, dropped_output_count=0)
        if self._interrupted:
            return InterruptionEvent(
                reason=self._interruption_reason or reason,
                dropped_output_count=0,
            )

        dropped = len(self._queued_output)
        self._queued_output.clear()
        self._interrupted = True
        self._interruption_reason = reason
        return InterruptionEvent(reason=reason, dropped_output_count=dropped)

    def finish_response(self) -> None:
        """Finish the current response and clear queued output."""

        self._queued_output.clear()
        self._response_active = False

    def reset(self) -> None:
        """Clear coordinator state for a new response."""

        self._response_active = False
        self._interrupted = False
        self._interruption_reason: str | None = None
        self._queued_output: deque[Any] = deque()
