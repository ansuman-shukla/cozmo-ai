"""Prometheus metrics registered by the backend service."""

from typing import Iterable

from prometheus_client import REGISTRY, Counter, Gauge

from cozmo_contracts.models import CallDisposition, CallSessionRecord, CallSessionStatus


def get_or_create_counter(name: str, documentation: str) -> Counter:
    """Reuse an existing counter when the module is imported multiple times in tests."""

    existing = REGISTRY._names_to_collectors.get(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Counter(name, documentation)


def get_or_create_gauge(name: str, documentation: str) -> Gauge:
    """Reuse an existing gauge when the module is imported multiple times in tests."""

    existing = REGISTRY._names_to_collectors.get(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Gauge(name, documentation)


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


def record_healthcheck() -> None:
    """Increment the backend health probe counter."""

    HEALTHCHECK_COUNTER.inc()


def record_call_session_snapshot(call_sessions: Iterable[CallSessionRecord]) -> None:
    """Project current persisted call-session state into low-cardinality backend gauges."""

    sessions = list(call_sessions)
    ACTIVE_CALLS_GAUGE.set(
        sum(1 for item in sessions if item.status == CallSessionStatus.ACTIVE)
    )
    FAILED_CALL_SETUPS_GAUGE.set(
        sum(1 for item in sessions if item.disposition == CallDisposition.SETUP_FAILED)
    )
