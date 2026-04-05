from pathlib import Path
import json

import pytest

from tests.load.config import LoadProfileError, load_profiles, parse_load_profiles


@pytest.mark.unit
def test_load_profile_parser_accepts_documented_25_50_100_profiles() -> None:
    profiles = load_profiles()

    assert [profile.name for profile in profiles] == ["25-calls", "50-calls", "100-calls"]
    assert [profile.concurrent_calls for profile in profiles] == [25, 50, 100]
    assert all(profile.max_avg_perceived_rtt_ms == 600 for profile in profiles)
    assert all(profile.max_p95_perceived_rtt_ms == 900 for profile in profiles)
    assert all(profile.max_failed_setup_rate_pct == 1 for profile in profiles)


@pytest.mark.unit
def test_load_profile_parser_rejects_non_increasing_concurrency() -> None:
    with pytest.raises(LoadProfileError, match="increase in concurrency order"):
        parse_load_profiles(
            [
                {"name": "first", "concurrent_calls": 50, "ramp_seconds": 30, "hold_seconds": 60},
                {"name": "second", "concurrent_calls": 25, "ramp_seconds": 30, "hold_seconds": 60},
            ]
        )


@pytest.mark.unit
def test_load_profile_parser_rejects_invalid_profile_file(tmp_path: Path) -> None:
    profile_path = tmp_path / "profiles.json"
    profile_path.write_text(json.dumps({"invalid": True}), encoding="utf-8")

    with pytest.raises(LoadProfileError, match="JSON list"):
        load_profiles(profile_path)
