"""Shared field validators and constrained types."""

from typing import Annotated

from pydantic import StringConstraints

RoomName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z0-9+][A-Za-z0-9_+-]*$",
    ),
]
ConfigId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    ),
]
PhoneNumber = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^\+[1-9]\d{7,14}$",
    ),
]
SipUri = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^sip:[^@\s]+@[^@\s]+$",
    ),
]
TransferTarget = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^(?:\+[1-9]\d{7,14}|sip:[^@\s]+@[^@\s]+)$",
    ),
]
NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
ProviderCallId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
