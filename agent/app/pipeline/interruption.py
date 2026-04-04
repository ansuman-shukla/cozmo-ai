"""Interruption coordinator placeholder."""


class InterruptionCoordinator:
    """Track whether the current agent response has been interrupted."""

    def __init__(self) -> None:
        self._interrupted = False

    @property
    def interrupted(self) -> bool:
        return self._interrupted

    def interrupt(self) -> None:
        self._interrupted = True

    def reset(self) -> None:
        self._interrupted = False

