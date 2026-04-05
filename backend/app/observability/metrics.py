"""Prometheus metrics registered by the backend service."""

from datetime import datetime
from typing import Iterable

from prometheus_client import REGISTRY, Counter, Gauge

from cozmo_contracts.models import CallDisposition, CallSessionRecord, CallSessionStatus


def get_or_create_counter(name: str, documentation: str) -> Counter:
    """Reuse an existing counter when the module is imported multiple times in tests."""

    existing = REGISTRY._names_to_collectors.get(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Counter(name, documentation)


def get_or_create_gauge(
    name: str,
    documentation: str,
    *,
    labelnames: tuple[str, ...] = (),
) -> Gauge:
    """Reuse an existing gauge when the module is imported multiple times in tests."""

    existing = REGISTRY._names_to_collectors.get(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Gauge(name, documentation, labelnames=labelnames)


HEALTHCHECK_COUNTER = get_or_create_counter(
    "cozmo_backend_healthcheck_total",
    "Count of backend health and metrics probes",
)
ACTIVE_CALLS_GAUGE = get_or_create_gauge(
    "cozmo_active_calls",
    "Count of active calls according to persisted session state",
)
FAILED_CALL_SETUPS_GAUGE = get_or_create_gauge(
    "cozmo_failed_call_setups_total",
    "Count of failed inbound call setups according to persisted session state",
)
FAILED_CALL_SETUP_RATE_PCT_GAUGE = get_or_create_gauge(
    "cozmo_failed_call_setup_rate_pct",
    "Percentage of persisted inbound call sessions that failed during setup",
)
PERSISTED_ROOM_JITTER_MS_GAUGE = get_or_create_gauge(
    "cozmo_persisted_room_jitter_ms",
    "Most recently persisted room jitter in milliseconds by agent config",
    labelnames=("agent_config_id",),
)
PERSISTED_ROOM_PACKET_LOSS_PCT_GAUGE = get_or_create_gauge(
    "cozmo_persisted_room_packet_loss_pct",
    "Most recently persisted room packet loss percentage by agent config",
    labelnames=("agent_config_id",),
)
PERSISTED_ROOM_MOS_ESTIMATE_GAUGE = get_or_create_gauge(
    "cozmo_persisted_room_mos_estimate",
    "Most recently persisted room MOS estimate by agent config",
    labelnames=("agent_config_id",),
)


def _call_sort_timestamp(item: CallSessionRecord) -> datetime:
    """Return the best available timestamp for ordering persisted call snapshots."""

    return item.connected_at or item.created_at


def record_healthcheck() -> None:
    """Increment the backend health probe counter."""

    HEALTHCHECK_COUNTER.inc()


def record_call_session_snapshot(call_sessions: Iterable[CallSessionRecord]) -> None:
    """Project current persisted call-session state into low-cardinality backend gauges."""

    sessions = list(call_sessions)
    failed_count = sum(1 for item in sessions if item.disposition == CallDisposition.SETUP_FAILED)
    latest_quality_by_config: dict[str, CallSessionRecord] = {}
    for item in sessions:
        quality = item.voice_quality
        if (
            quality.avg_jitter_ms is None
            and quality.packet_loss_pct is None
            and quality.mos_estimate is None
        ):
            continue
        existing = latest_quality_by_config.get(item.agent_config_id)
        if existing is None or _call_sort_timestamp(item) >= _call_sort_timestamp(existing):
            latest_quality_by_config[item.agent_config_id] = item

    ACTIVE_CALLS_GAUGE.set(
        sum(1 for item in sessions if item.status == CallSessionStatus.ACTIVE)
    )
    FAILED_CALL_SETUPS_GAUGE.set(failed_count)
    FAILED_CALL_SETUP_RATE_PCT_GAUGE.set(
        (failed_count / len(sessions) * 100.0) if sessions else 0.0
    )
    PERSISTED_ROOM_JITTER_MS_GAUGE.clear()
    PERSISTED_ROOM_PACKET_LOSS_PCT_GAUGE.clear()
    PERSISTED_ROOM_MOS_ESTIMATE_GAUGE.clear()
    for agent_config_id, item in latest_quality_by_config.items():
        quality = item.voice_quality
        if quality.avg_jitter_ms is not None:
            PERSISTED_ROOM_JITTER_MS_GAUGE.labels(agent_config_id=agent_config_id).set(quality.avg_jitter_ms)
        if quality.packet_loss_pct is not None:
            PERSISTED_ROOM_PACKET_LOSS_PCT_GAUGE.labels(agent_config_id=agent_config_id).set(quality.packet_loss_pct)
        if quality.mos_estimate is not None:
            PERSISTED_ROOM_MOS_ESTIMATE_GAUGE.labels(agent_config_id=agent_config_id).set(quality.mos_estimate)
