"""Synthetic stepped-load runner for local validation."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from statistics import fmean
from typing import Awaitable, Callable

from tests.load.config import DEFAULT_PROFILE_PATH, LoadProfile, load_profiles


@dataclass(frozen=True, slots=True)
class SyntheticCallResult:
    """Outcome of one synthetic call attempt."""

    success: bool
    perceived_rtt_ms: float
    setup_failed: bool = False


@dataclass(frozen=True, slots=True)
class LoadRunReport:
    """Persistable summary for one stepped load profile."""

    profile_name: str
    concurrent_calls: int
    success_count: int
    failure_count: int
    setup_failure_count: int
    average_perceived_rtt_ms: float | None
    p95_perceived_rtt_ms: float | None
    max_perceived_rtt_ms: float | None
    started_at: datetime
    completed_at: datetime

    def as_dict(self) -> dict[str, object]:
        """Serialize the report into a JSON-friendly mapping."""

        payload = asdict(self)
        payload["started_at"] = self.started_at.isoformat()
        payload["completed_at"] = self.completed_at.isoformat()
        return payload


def _percentile(sorted_values: list[float], percentile: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = int(round((len(sorted_values) - 1) * percentile))
    return sorted_values[max(0, min(index, len(sorted_values) - 1))]


class SyntheticLoadRunner:
    """Run stepped synthetic call profiles and write JSON reports."""

    async def run_profile(
        self,
        profile: LoadProfile,
        *,
        call_factory: Callable[[int, LoadProfile], Awaitable[SyntheticCallResult]],
    ) -> LoadRunReport:
        """Run one stepped profile and aggregate latency and failure outputs."""

        started_at = datetime.now(UTC)
        ramp_interval = profile.ramp_seconds / profile.concurrent_calls

        async def invoke(call_index: int) -> SyntheticCallResult:
            await asyncio.sleep(ramp_interval * call_index)
            return await call_factory(call_index, profile)

        results = await asyncio.gather(*(invoke(index) for index in range(profile.concurrent_calls)))
        completed_at = datetime.now(UTC)

        latencies = sorted(result.perceived_rtt_ms for result in results if result.success)
        success_count = sum(1 for result in results if result.success)
        failure_count = len(results) - success_count
        setup_failure_count = sum(1 for result in results if result.setup_failed)
        return LoadRunReport(
            profile_name=profile.name,
            concurrent_calls=profile.concurrent_calls,
            success_count=success_count,
            failure_count=failure_count,
            setup_failure_count=setup_failure_count,
            average_perceived_rtt_ms=float(fmean(latencies)) if latencies else None,
            p95_perceived_rtt_ms=_percentile(latencies, 0.95),
            max_perceived_rtt_ms=max(latencies) if latencies else None,
            started_at=started_at,
            completed_at=completed_at,
        )

    def write_report(self, report: LoadRunReport, *, output_dir: str | Path) -> Path:
        """Persist one load-run report as JSON."""

        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        output_path = destination / f"{report.profile_name}.json"
        output_path.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
        return output_path


async def simulate_call(call_index: int, profile: LoadProfile) -> SyntheticCallResult:
    """Deterministic local simulator used when no real call driver is attached."""

    await asyncio.sleep(0.01)
    setup_failed = call_index % 97 == 0 and profile.concurrent_calls >= 100
    success = not setup_failed
    perceived_rtt_ms = 280.0 + min(profile.concurrent_calls * 3.0, 380.0) + float(call_index % 7) * 9.5
    return SyntheticCallResult(
        success=success,
        perceived_rtt_ms=perceived_rtt_ms,
        setup_failed=setup_failed,
    )


async def _run_cli(profile_path: Path, output_dir: Path) -> list[Path]:
    profiles = load_profiles(profile_path)
    runner = SyntheticLoadRunner()
    outputs: list[Path] = []
    for profile in profiles:
        report = await runner.run_profile(profile, call_factory=simulate_call)
        outputs.append(runner.write_report(report, output_dir=output_dir))
    return outputs


def main() -> None:
    """Run the stepped synthetic load profiles and write JSON summaries."""

    parser = argparse.ArgumentParser(description="Run stepped synthetic load profiles.")
    parser.add_argument(
        "--profiles",
        default=str(DEFAULT_PROFILE_PATH),
        help="Path to the load profile JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/load",
        help="Directory where per-profile JSON reports should be written.",
    )
    args = parser.parse_args()
    outputs = asyncio.run(_run_cli(Path(args.profiles), Path(args.output_dir)))
    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
