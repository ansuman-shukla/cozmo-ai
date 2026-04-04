"""Prometheus-style counters for the worker skeleton."""

from prometheus_client import REGISTRY, Counter


def get_or_create_counter(name: str, documentation: str, *, labelnames: tuple[str, ...] = ()) -> Counter:
    """Reuse an existing counter when the module is imported multiple times in tests."""

    existing = REGISTRY._names_to_collectors.get(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Counter(name, documentation, labelnames=labelnames)


WORKER_STARTS = get_or_create_counter(
    "cozmo_agent_worker_starts_total",
    "Count of worker-start events",
    labelnames=("worker_name",),
)
JOB_BOOTSTRAPS = get_or_create_counter(
    "cozmo_agent_job_bootstraps_total",
    "Count of per-call bootstrap completions",
    labelnames=("worker_name", "agent_config_id"),
)
JOB_BOOTSTRAP_FAILURES = get_or_create_counter(
    "cozmo_agent_job_bootstrap_failures_total",
    "Count of per-call bootstrap failures",
    labelnames=("worker_name", "reason"),
)
GREETING_PUBLISHES = get_or_create_counter(
    "cozmo_agent_greeting_publishes_total",
    "Count of successful greeting-audio publications",
    labelnames=("worker_name", "agent_config_id"),
)
GREETING_PUBLISH_FAILURES = get_or_create_counter(
    "cozmo_agent_greeting_publish_failures_total",
    "Count of greeting-audio publish failures",
    labelnames=("worker_name", "reason"),
)


def record_worker_start(worker_name: str) -> None:
    """Increment the worker-start metric for the named worker."""

    WORKER_STARTS.labels(worker_name=worker_name).inc()


def record_job_bootstrap(worker_name: str, agent_config_id: str) -> None:
    """Increment the successful bootstrap metric."""

    JOB_BOOTSTRAPS.labels(worker_name=worker_name, agent_config_id=agent_config_id).inc()


def record_job_bootstrap_failure(worker_name: str, reason: str) -> None:
    """Increment the failed bootstrap metric."""

    JOB_BOOTSTRAP_FAILURES.labels(worker_name=worker_name, reason=reason).inc()


def record_greeting_publish(worker_name: str, agent_config_id: str) -> None:
    """Increment the successful greeting-publish metric."""

    GREETING_PUBLISHES.labels(worker_name=worker_name, agent_config_id=agent_config_id).inc()


def record_greeting_publish_failure(worker_name: str, reason: str) -> None:
    """Increment the failed greeting-publish metric."""

    GREETING_PUBLISH_FAILURES.labels(worker_name=worker_name, reason=reason).inc()
