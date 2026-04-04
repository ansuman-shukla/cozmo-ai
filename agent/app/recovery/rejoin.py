"""Worker recovery placeholder."""

from dataclasses import dataclass


@dataclass(slots=True)
class RejoinCoordinator:
    """Mark a room as recoverable until real recovery flows are added."""

    room_name: str
    recoverable: bool = True

