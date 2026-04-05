"""Load-profile parsing for stepped synthetic validation runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Iterable


DEFAULT_PROFILE_PATH = Path(__file__).with_name("profiles.json")


class LoadProfileError(ValueError):
    """Raised when a configured load profile is invalid."""


@dataclass(frozen=True, slots=True)
class LoadProfile:
    """One stepped concurrency profile used for synthetic load validation."""

    name: str
    concurrent_calls: int
    ramp_seconds: int
    hold_seconds: int
    max_avg_perceived_rtt_ms: float = 600.0
    max_p95_perceived_rtt_ms: float = 900.0
    max_failed_setup_rate_pct: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        """Serialize the profile into a JSON-friendly mapping."""

        return asdict(self)


def _require_positive_int(name: str, value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise LoadProfileError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise LoadProfileError(f"{name} must be greater than zero")
    return parsed


def _require_positive_float(name: str, value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise LoadProfileError(f"{name} must be a number") from exc
    if parsed <= 0:
        raise LoadProfileError(f"{name} must be greater than zero")
    return parsed


def parse_load_profiles(raw_profiles: Iterable[dict[str, Any]]) -> tuple[LoadProfile, ...]:
    """Validate and normalize stepped concurrency profiles."""

    items = list(raw_profiles)
    if not items:
        raise LoadProfileError("At least one load profile is required")

    parsed: list[LoadProfile] = []
    seen_names: set[str] = set()
    previous_concurrency = 0
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise LoadProfileError(f"Profile at index {index} must be a mapping")

        name = str(item.get("name") or "").strip()
        if not name:
            raise LoadProfileError(f"Profile at index {index} is missing a name")
        if name in seen_names:
            raise LoadProfileError(f"Duplicate load profile name: {name}")

        concurrent_calls = _require_positive_int("concurrent_calls", item.get("concurrent_calls"))
        if concurrent_calls <= previous_concurrency:
            raise LoadProfileError("Load profiles must increase in concurrency order")

        profile = LoadProfile(
            name=name,
            concurrent_calls=concurrent_calls,
            ramp_seconds=_require_positive_int("ramp_seconds", item.get("ramp_seconds")),
            hold_seconds=_require_positive_int("hold_seconds", item.get("hold_seconds")),
            max_avg_perceived_rtt_ms=_require_positive_float(
                "max_avg_perceived_rtt_ms",
                item.get("max_avg_perceived_rtt_ms", 600),
            ),
            max_p95_perceived_rtt_ms=_require_positive_float(
                "max_p95_perceived_rtt_ms",
                item.get("max_p95_perceived_rtt_ms", 900),
            ),
            max_failed_setup_rate_pct=_require_positive_float(
                "max_failed_setup_rate_pct",
                item.get("max_failed_setup_rate_pct", 1),
            ),
        )
        parsed.append(profile)
        seen_names.add(name)
        previous_concurrency = concurrent_calls

    return tuple(parsed)


def load_profiles(path: str | Path = DEFAULT_PROFILE_PATH) -> tuple[LoadProfile, ...]:
    """Load and validate stepped concurrency profiles from JSON."""

    profile_path = Path(path)
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise LoadProfileError("Profile file must contain a JSON list")
    return parse_load_profiles(payload)
