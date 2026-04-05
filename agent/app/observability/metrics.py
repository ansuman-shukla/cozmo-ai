"""Prometheus-style metrics for the worker skeleton."""

from threading import Lock

from prometheus_client import REGISTRY, Counter, Gauge, Histogram

from cozmo_contracts.models import TurnLatencyMetrics, VoiceQualityMetrics


def get_or_create_counter(name: str, documentation: str, *, labelnames: tuple[str, ...] = ()) -> Counter:
    """Reuse an existing counter when the module is imported multiple times in tests."""

    existing = REGISTRY._names_to_collectors.get(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Counter(name, documentation, labelnames=labelnames)


def get_or_create_histogram(
    name: str,
    documentation: str,
    *,
    labelnames: tuple[str, ...] = (),
    buckets: tuple[float, ...] = (25, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
) -> Histogram:
    """Reuse an existing histogram when the module is imported multiple times in tests."""

    existing = REGISTRY._names_to_collectors.get(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Histogram(name, documentation, labelnames=labelnames, buckets=buckets)


def get_or_create_gauge(name: str, documentation: str, *, labelnames: tuple[str, ...] = ()) -> Gauge:
    """Reuse an existing gauge when the module is imported multiple times in tests."""

    existing = REGISTRY._names_to_collectors.get(name)
    if existing is not None:
        return existing  # type: ignore[return-value]
    return Gauge(name, documentation, labelnames=labelnames)


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
RESPONSE_INTERRUPTS = get_or_create_counter(
    "cozmo_agent_response_interruptions_total",
    "Count of response interruptions caused by caller speech or other events",
    labelnames=("worker_name", "reason"),
)
INTERRUPTED_AGENT_TURNS = get_or_create_counter(
    "cozmo_agent_interrupted_agent_turns_total",
    "Count of agent transcript turns later marked as interrupted",
    labelnames=("worker_name", "agent_config_id"),
)
TURN_LATENCY_MS = get_or_create_histogram(
    "cozmo_agent_turn_latency_ms",
    "Per-turn latency observations by stage in milliseconds",
    labelnames=("worker_name", "agent_config_id", "stage"),
)
AGENT_JOBS_ACTIVE = get_or_create_gauge(
    "cozmo_agent_jobs_active",
    "Number of active agent jobs running on the worker",
    labelnames=("worker_name",),
)
WORKER_JOB_QUEUE_DEPTH = get_or_create_gauge(
    "cozmo_worker_job_queue_depth",
    "Number of jobs above the configured verified worker capacity",
    labelnames=("worker_name",),
)
WORKER_CPU_UTILIZATION = get_or_create_gauge(
    "cozmo_worker_cpu_utilization",
    "Current worker-process CPU utilization as a percentage of host capacity",
    labelnames=("worker_name",),
)
WORKER_MEMORY_UTILIZATION = get_or_create_gauge(
    "cozmo_worker_memory_utilization",
    "Current worker-process RSS memory utilization as a percentage of host memory",
    labelnames=("worker_name",),
)
CALL_SETUP_SECONDS = get_or_create_histogram(
    "cozmo_call_setup_seconds",
    "Observed worker bootstrap time from job start to ready state in seconds",
    labelnames=("worker_name", "agent_config_id"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
PIPELINE_RTT_SECONDS = get_or_create_histogram(
    "cozmo_pipeline_rtt_seconds",
    "Observed per-turn pipeline round-trip time in seconds",
    labelnames=("worker_name", "agent_config_id"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
PERCEIVED_RTT_SECONDS = get_or_create_histogram(
    "cozmo_perceived_rtt_seconds",
    "Observed per-turn perceived round-trip time in seconds",
    labelnames=("worker_name", "agent_config_id"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
STT_LATENCY_SECONDS = get_or_create_histogram(
    "cozmo_stt_latency_seconds",
    "Observed speech-to-text latency in seconds",
    labelnames=("worker_name", "agent_config_id"),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
LLM_TTFT_SECONDS = get_or_create_histogram(
    "cozmo_llm_ttft_seconds",
    "Observed language-model time-to-first-token in seconds",
    labelnames=("worker_name", "agent_config_id"),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
TTS_FIRST_AUDIO_SECONDS = get_or_create_histogram(
    "cozmo_tts_first_audio_seconds",
    "Observed text-to-speech first-audio latency in seconds",
    labelnames=("worker_name", "agent_config_id"),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)
AGENT_RECOVERIES = get_or_create_counter(
    "cozmo_agent_recoveries_total",
    "Count of replacement-job recovery plans requested by the worker",
    labelnames=("worker_name",),
)
ROOM_JITTER_MS = get_or_create_gauge(
    "cozmo_room_jitter_ms",
    "Latest aggregated room jitter in milliseconds for the active call",
    labelnames=("worker_name", "agent_config_id"),
)
ROOM_PACKET_LOSS_PCT = get_or_create_gauge(
    "cozmo_room_packet_loss_pct",
    "Latest aggregated room packet loss percentage for the active call",
    labelnames=("worker_name", "agent_config_id"),
)
ROOM_MOS_ESTIMATE = get_or_create_gauge(
    "cozmo_room_mos_estimate",
    "Latest estimated MOS score for the active call",
    labelnames=("worker_name", "agent_config_id"),
)

_ACTIVE_JOBS: dict[str, int] = {}
_ACTIVE_JOBS_LOCK = Lock()


def _ms_to_seconds(value: float | None) -> float | None:
    """Convert a millisecond value into seconds when present."""

    if value is None:
        return None
    return value / 1000.0


def calculate_pipeline_rtt_ms(
    *,
    stt_ms: float | None,
    llm_ttft_ms: float | None,
    tts_first_audio_ms: float | None,
) -> float | None:
    """Compute pipeline RTT from stage latencies when at least one stage is present."""

    present = [value for value in (stt_ms, llm_ttft_ms, tts_first_audio_ms) if value is not None]
    if not present:
        return None
    return sum(present)


def calculate_perceived_rtt_ms(
    *,
    endpoint_ms: float | None,
    stt_ms: float | None,
    llm_ttft_ms: float | None,
    tts_first_audio_ms: float | None,
) -> float | None:
    """Compute caller-perceived RTT including endpointing time when available."""

    present = [value for value in (endpoint_ms, stt_ms, llm_ttft_ms, tts_first_audio_ms) if value is not None]
    if not present:
        return None
    return sum(present)


def _set_active_job_metrics(worker_name: str, *, active_jobs: int, max_jobs: int) -> None:
    """Project the current worker concurrency into active-job and queue-depth gauges."""

    AGENT_JOBS_ACTIVE.labels(worker_name=worker_name).set(active_jobs)
    WORKER_JOB_QUEUE_DEPTH.labels(worker_name=worker_name).set(max(active_jobs - max_jobs, 0))


def calculate_cpu_utilization_pct(
    *,
    cpu_seconds_delta: float,
    wall_seconds_delta: float,
    cpu_count: int,
) -> float:
    """Estimate worker CPU utilization as a percent of total host CPU capacity."""

    if wall_seconds_delta <= 0 or cpu_count <= 0:
        return 0.0
    return max(0.0, min(cpu_seconds_delta / (wall_seconds_delta * cpu_count) * 100.0, 100.0))


def calculate_memory_utilization_pct(
    *,
    rss_bytes: int,
    total_memory_bytes: int,
) -> float:
    """Estimate worker RSS memory utilization as a percent of host memory."""

    if total_memory_bytes <= 0:
        return 0.0
    return max(0.0, min(rss_bytes / total_memory_bytes * 100.0, 100.0))


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


def record_response_interrupt(worker_name: str, reason: str) -> None:
    """Increment the interruption counter for the supplied reason."""

    RESPONSE_INTERRUPTS.labels(worker_name=worker_name, reason=reason).inc()


def record_interrupted_agent_turn(worker_name: str, agent_config_id: str) -> None:
    """Increment the interrupted-agent-turn counter."""

    INTERRUPTED_AGENT_TURNS.labels(
        worker_name=worker_name,
        agent_config_id=agent_config_id,
    ).inc()


def record_job_started(worker_name: str, *, max_jobs: int) -> None:
    """Increment active-job state for the worker and update saturation gauges."""

    with _ACTIVE_JOBS_LOCK:
        active_jobs = _ACTIVE_JOBS.get(worker_name, 0) + 1
        _ACTIVE_JOBS[worker_name] = active_jobs
    _set_active_job_metrics(worker_name, active_jobs=active_jobs, max_jobs=max_jobs)


def record_job_finished(worker_name: str, *, max_jobs: int) -> None:
    """Decrement active-job state for the worker and update saturation gauges."""

    with _ACTIVE_JOBS_LOCK:
        active_jobs = max(_ACTIVE_JOBS.get(worker_name, 0) - 1, 0)
        if active_jobs == 0:
            _ACTIVE_JOBS.pop(worker_name, None)
        else:
            _ACTIVE_JOBS[worker_name] = active_jobs
    _set_active_job_metrics(worker_name, active_jobs=active_jobs, max_jobs=max_jobs)


def record_call_setup(worker_name: str, agent_config_id: str, *, call_setup_ms: float) -> None:
    """Observe one successful call bootstrap duration."""

    CALL_SETUP_SECONDS.labels(
        worker_name=worker_name,
        agent_config_id=agent_config_id,
    ).observe(call_setup_ms / 1000.0)


def record_recovery(worker_name: str) -> None:
    """Increment the replacement-job recovery counter."""

    AGENT_RECOVERIES.labels(worker_name=worker_name).inc()


def record_worker_system_utilization(
    worker_name: str,
    *,
    cpu_utilization_pct: float,
    memory_utilization_pct: float,
) -> None:
    """Set the current worker-process CPU and memory utilization gauges."""

    WORKER_CPU_UTILIZATION.labels(worker_name=worker_name).set(cpu_utilization_pct)
    WORKER_MEMORY_UTILIZATION.labels(worker_name=worker_name).set(memory_utilization_pct)


def record_room_quality(
    worker_name: str,
    agent_config_id: str,
    quality: VoiceQualityMetrics,
) -> None:
    """Set the latest low-cardinality room-quality gauges for the active call."""

    if quality.avg_jitter_ms is not None:
        ROOM_JITTER_MS.labels(
            worker_name=worker_name,
            agent_config_id=agent_config_id,
        ).set(quality.avg_jitter_ms)
    if quality.packet_loss_pct is not None:
        ROOM_PACKET_LOSS_PCT.labels(
            worker_name=worker_name,
            agent_config_id=agent_config_id,
        ).set(quality.packet_loss_pct)
    if quality.mos_estimate is not None:
        ROOM_MOS_ESTIMATE.labels(
            worker_name=worker_name,
            agent_config_id=agent_config_id,
        ).set(quality.mos_estimate)


def record_turn_latency_metrics(
    worker_name: str,
    agent_config_id: str,
    latency: TurnLatencyMetrics,
) -> None:
    """Observe available per-turn latency values under stage labels."""

    values = {
        "endpoint_ms": latency.endpoint_ms,
        "stt_ms": latency.stt_ms,
        "llm_ttft_ms": latency.llm_ttft_ms,
        "tts_first_audio_ms": latency.tts_first_audio_ms,
        "pipeline_rtt_ms": latency.pipeline_rtt_ms,
        "perceived_rtt_ms": latency.perceived_rtt_ms,
    }
    for stage, value in values.items():
        if value is None:
            continue
        TURN_LATENCY_MS.labels(
            worker_name=worker_name,
            agent_config_id=agent_config_id,
            stage=stage,
        ).observe(value)

    stage_histograms = {
        PIPELINE_RTT_SECONDS: latency.pipeline_rtt_ms,
        PERCEIVED_RTT_SECONDS: latency.perceived_rtt_ms,
        STT_LATENCY_SECONDS: latency.stt_ms,
        LLM_TTFT_SECONDS: latency.llm_ttft_ms,
        TTS_FIRST_AUDIO_SECONDS: latency.tts_first_audio_ms,
    }
    for histogram, value in stage_histograms.items():
        seconds = _ms_to_seconds(value)
        if seconds is None:
            continue
        histogram.labels(
            worker_name=worker_name,
            agent_config_id=agent_config_id,
        ).observe(seconds)
