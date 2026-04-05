"""Room-quality sampling and persistence helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from statistics import fmean
from typing import Any, Iterable

from cozmo_contracts.models import VoiceQualityMetrics

from app.call_state import CallStateSink
from app.observability.metrics import record_room_quality

LOGGER = logging.getLogger(__name__)


def _mean(values: Iterable[float]) -> float | None:
    """Return the arithmetic mean of a non-empty float iterable."""

    values = tuple(values)
    if not values:
        return None
    return float(fmean(values))


def _extract_nested_stat(sample: Any, field_name: str) -> Any | None:
    """Return a populated nested stats message when the field is present."""

    if sample is None:
        return None
    has_field = getattr(sample, "HasField", None)
    if callable(has_field):
        try:
            if has_field(field_name):
                return getattr(sample, field_name)
            return None
        except (TypeError, ValueError):
            pass
    nested = getattr(sample, field_name, None)
    if nested is None:
        return None
    list_fields = getattr(nested, "ListFields", None)
    if callable(list_fields):
        try:
            if not list_fields():
                return None
        except TypeError:
            pass
    return nested


def _nested_value(sample: Any, *path: str) -> Any | None:
    """Return a nested attribute when every hop is populated."""

    current = sample
    for field_name in path:
        current = _extract_nested_stat(current, field_name)
        if current is None:
            return None
    return current


def estimate_mos(
    *,
    jitter_ms: float | None,
    packet_loss_pct: float | None,
    round_trip_time_ms: float | None,
) -> float | None:
    """Estimate MOS with a simple latency-and-loss weighted approximation."""

    if jitter_ms is None and packet_loss_pct is None and round_trip_time_ms is None:
        return None

    jitter_ms = max(jitter_ms or 0.0, 0.0)
    packet_loss_pct = max(packet_loss_pct or 0.0, 0.0)
    round_trip_time_ms = max(round_trip_time_ms or 0.0, 0.0)
    effective_latency = round_trip_time_ms + (2.0 * jitter_ms) + 10.0
    if effective_latency <= 160.0:
        rating = 93.2 - (effective_latency / 40.0)
    else:
        rating = 93.2 - ((effective_latency - 120.0) / 10.0)
    rating -= packet_loss_pct * 2.5
    rating = max(0.0, min(rating, 100.0))
    mos = 1.0 + (0.035 * rating) + (7.0e-6 * rating * (rating - 60.0) * (100.0 - rating))
    return round(max(1.0, min(mos, 4.5)), 2)


def summarize_room_quality(rtc_stats: Any) -> VoiceQualityMetrics:
    """Aggregate LiveKit RTC stats into a persisted room-quality summary."""

    jitter_ms_values: list[float] = []
    packet_totals = {"received": 0.0, "lost": 0.0}
    fallback_loss_pct: list[float] = []
    round_trip_ms_values: list[float] = []

    for sample in tuple(getattr(rtc_stats, "publisher_stats", ()) or ()) + tuple(
        getattr(rtc_stats, "subscriber_stats", ()) or ()
    ):
        inbound = _extract_nested_stat(sample, "inbound_rtp")
        if inbound is not None:
            inbound_received = _nested_value(inbound, "received")
            jitter = getattr(inbound_received, "jitter", None) if inbound_received is not None else getattr(inbound, "jitter", None)
            if jitter is not None:
                jitter_ms_values.append(float(jitter) * 1000.0)
            packets_received = (
                getattr(inbound_received, "packets_received", None)
                if inbound_received is not None
                else getattr(inbound, "packets_received", None)
            )
            packets_lost = (
                getattr(inbound_received, "packets_lost", None)
                if inbound_received is not None
                else getattr(inbound, "packets_lost", None)
            )
            if packets_received is not None and packets_lost is not None:
                packet_totals["received"] += float(packets_received)
                packet_totals["lost"] += float(packets_lost)

        remote_inbound = _extract_nested_stat(sample, "remote_inbound_rtp")
        if remote_inbound is not None:
            remote_inbound_stats = _nested_value(remote_inbound, "remote_inbound")
            round_trip_time = (
                getattr(remote_inbound_stats, "round_trip_time", None)
                if remote_inbound_stats is not None
                else getattr(remote_inbound, "round_trip_time", None)
            )
            if round_trip_time is not None:
                round_trip_ms_values.append(float(round_trip_time) * 1000.0)
            fraction_lost = (
                getattr(remote_inbound_stats, "fraction_lost", None)
                if remote_inbound_stats is not None
                else getattr(remote_inbound, "fraction_lost", None)
            )
            if fraction_lost is not None:
                fallback_loss_pct.append(float(fraction_lost) * 100.0)

        candidate_pair = _extract_nested_stat(sample, "candidate_pair")
        if candidate_pair is not None:
            candidate_pair_stats = _nested_value(candidate_pair, "candidate_pair")
            current_round_trip_time = (
                getattr(candidate_pair_stats, "current_round_trip_time", None)
                if candidate_pair_stats is not None
                else getattr(candidate_pair, "current_round_trip_time", None)
            )
            if current_round_trip_time is not None:
                round_trip_ms_values.append(float(current_round_trip_time) * 1000.0)

    avg_jitter_ms = _mean(jitter_ms_values)
    packet_loss_pct = None
    if (packet_totals["received"] + packet_totals["lost"]) > 0:
        packet_loss_pct = (packet_totals["lost"] / (packet_totals["received"] + packet_totals["lost"])) * 100.0
    else:
        packet_loss_pct = _mean(fallback_loss_pct)

    mos_estimate = estimate_mos(
        jitter_ms=avg_jitter_ms,
        packet_loss_pct=packet_loss_pct,
        round_trip_time_ms=_mean(round_trip_ms_values),
    )
    return VoiceQualityMetrics(
        avg_jitter_ms=round(avg_jitter_ms, 3) if avg_jitter_ms is not None else None,
        packet_loss_pct=round(packet_loss_pct, 3) if packet_loss_pct is not None else None,
        mos_estimate=mos_estimate,
    )


@dataclass(slots=True)
class RoomQualityMonitor:
    """Periodic room-quality sampler for an active LiveKit room."""

    room: Any
    worker_name: str
    agent_config_id: str
    room_name: str
    poll_interval_ms: int = 5000
    call_state_sink: CallStateSink | None = None

    async def sample_once(self) -> VoiceQualityMetrics | None:
        """Collect one quality snapshot, publish gauges, and persist it."""

        rtc_stats = await self.room.get_rtc_stats()
        quality = summarize_room_quality(rtc_stats)
        if (
            quality.avg_jitter_ms is None
            and quality.packet_loss_pct is None
            and quality.mos_estimate is None
        ):
            return None

        record_room_quality(self.worker_name, self.agent_config_id, quality)
        if self.call_state_sink is not None:
            await asyncio.to_thread(
                self.call_state_sink.update_voice_quality,
                self.room_name,
                quality,
            )
        return quality

    async def run(self) -> None:
        """Continuously sample quality until the task is cancelled."""

        while True:
            try:
                await self.sample_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(
                    "failed to sample room quality",
                    extra={
                        "room_name": self.room_name,
                        "agent_config_id": self.agent_config_id,
                    },
                )
            await asyncio.sleep(self.poll_interval_ms / 1000.0)
