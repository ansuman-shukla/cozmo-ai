"""Prometheus metrics registered by the backend service."""

from prometheus_client import REGISTRY, Counter


def get_or_create_counter(name: str, documentation: str) -> Counter:
    """Reuse an existing counter when the module is imported multiple times in tests."""

    existing = REGISTRY._names_to_collectors.get(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Counter(name, documentation)


HEALTHCHECK_COUNTER = get_or_create_counter(
    "cozmo_backend_healthcheck_total",
    "Count of backend health and metrics probes",
)


def record_healthcheck() -> None:
    """Increment the backend health probe counter."""

    HEALTHCHECK_COUNTER.inc()
