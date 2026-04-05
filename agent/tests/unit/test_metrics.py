from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest


def load_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[2] / relative_path
    spec = spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def add_repo_paths() -> tuple[str, str]:
    agent_root = str(Path(__file__).resolve().parents[2])
    contracts_root = str(Path(__file__).resolve().parents[3] / "contracts")
    sys.path.insert(0, agent_root)
    sys.path.insert(0, contracts_root)
    return agent_root, contracts_root


def remove_repo_paths(*paths: str) -> None:
    for path in paths:
        if path in sys.path:
            sys.path.remove(path)
    for name in list(sys.modules):
        if (
            name == "app"
            or name.startswith("app.")
            or name == "cozmo_contracts"
            or name.startswith("cozmo_contracts.")
            or name == "agent_metrics_unit"
        ):
            sys.modules.pop(name, None)


def histogram_count(histogram, expected_labels: dict[str, str]) -> float:
    for metric in histogram.collect():
        for sample in metric.samples:
            if not sample.name.endswith("_count"):
                continue
            if sample.labels == expected_labels:
                return sample.value
    return 0.0


def gauge_value(gauge, expected_labels: dict[str, str]) -> float:
    for metric in gauge.collect():
        for sample in metric.samples:
            if sample.name != gauge._name:
                continue
            if sample.labels == expected_labels:
                return sample.value
    return 0.0


@pytest.mark.unit
def test_latency_calculators_compute_pipeline_and_perceived_rtt() -> None:
    inserted_paths = add_repo_paths()

    try:
        metrics = load_module("agent_metrics_unit", "app/observability/metrics.py")

        assert metrics.calculate_pipeline_rtt_ms(
            stt_ms=120.0,
            llm_ttft_ms=310.0,
            tts_first_audio_ms=90.0,
        ) == 520.0
        assert metrics.calculate_perceived_rtt_ms(
            endpoint_ms=180.0,
            stt_ms=120.0,
            llm_ttft_ms=310.0,
            tts_first_audio_ms=90.0,
        ) == 700.0
        assert metrics.calculate_cpu_utilization_pct(
            cpu_seconds_delta=0.4,
            wall_seconds_delta=1.0,
            cpu_count=4,
        ) == 10.0
        assert metrics.calculate_memory_utilization_pct(
            rss_bytes=512,
            total_memory_bytes=2048,
        ) == 25.0
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
def test_latency_and_setup_metrics_use_stable_low_cardinality_labels() -> None:
    inserted_paths = add_repo_paths()

    try:
        metrics = load_module("agent_metrics_unit", "app/observability/metrics.py")
        from cozmo_contracts.models import TurnLatencyMetrics

        latency = TurnLatencyMetrics(
            stt_ms=110.0,
            llm_ttft_ms=220.0,
            tts_first_audio_ms=55.0,
            pipeline_rtt_ms=385.0,
            perceived_rtt_ms=385.0,
        )

        metrics.record_turn_latency_metrics("cozmo-agent-obsv", "main-inbound", latency)
        metrics.record_call_setup("cozmo-agent-obsv", "main-inbound", call_setup_ms=640.0)
        metrics.record_job_started("cozmo-agent-obsv", max_jobs=8)
        metrics.record_job_finished("cozmo-agent-obsv", max_jobs=8)
        metrics.record_worker_system_utilization(
            "cozmo-agent-obsv",
            cpu_utilization_pct=12.5,
            memory_utilization_pct=33.3,
        )

        assert histogram_count(
            metrics.PIPELINE_RTT_SECONDS,
            {"worker_name": "cozmo-agent-obsv", "agent_config_id": "main-inbound"},
        ) >= 1.0
        assert histogram_count(
            metrics.CALL_SETUP_SECONDS,
            {"worker_name": "cozmo-agent-obsv", "agent_config_id": "main-inbound"},
        ) >= 1.0
        assert gauge_value(
            metrics.AGENT_JOBS_ACTIVE,
            {"worker_name": "cozmo-agent-obsv"},
        ) == 0.0
        assert gauge_value(
            metrics.WORKER_JOB_QUEUE_DEPTH,
            {"worker_name": "cozmo-agent-obsv"},
        ) == 0.0
        assert gauge_value(
            metrics.WORKER_CPU_UTILIZATION,
            {"worker_name": "cozmo-agent-obsv"},
        ) == 12.5
        assert gauge_value(
            metrics.WORKER_MEMORY_UTILIZATION,
            {"worker_name": "cozmo-agent-obsv"},
        ) == 33.3
    finally:
        remove_repo_paths(*inserted_paths)
