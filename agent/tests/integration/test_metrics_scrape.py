from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from urllib.request import urlopen

import pytest
from prometheus_client import start_http_server


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
            or name in {"agent_metrics_scrape", "agent_quality_scrape"}
        ):
            sys.modules.pop(name, None)


@pytest.mark.integration
def test_worker_prometheus_scrape_exposes_required_metric_set() -> None:
    inserted_paths = add_repo_paths()

    try:
        metrics = load_module("agent_metrics_scrape", "app/observability/metrics.py")
        from cozmo_contracts.models import TurnLatencyMetrics, VoiceQualityMetrics

        worker_name = "cozmo-agent-scrape"
        config_id = "main-inbound"
        metrics.initialize_worker_runtime_metrics(worker_name, max_jobs=8)
        metrics.record_worker_start(worker_name)
        metrics.record_job_started(worker_name, max_jobs=8)
        metrics.record_call_setup(worker_name, config_id, call_setup_ms=850.0)
        metrics.record_turn_latency_metrics(
            worker_name,
            config_id,
            TurnLatencyMetrics(
                stt_ms=120.0,
                llm_ttft_ms=240.0,
                tts_first_audio_ms=90.0,
                pipeline_rtt_ms=450.0,
                perceived_rtt_ms=590.0,
            ),
        )
        metrics.record_recovery(worker_name)
        metrics.record_worker_system_utilization(
            worker_name,
            cpu_utilization_pct=18.0,
            memory_utilization_pct=27.0,
        )
        metrics.record_room_quality(
            worker_name,
            config_id,
            VoiceQualityMetrics(
                avg_jitter_ms=14.0,
                packet_loss_pct=0.7,
                mos_estimate=4.12,
            ),
        )

        server, _thread = start_http_server(0, addr="127.0.0.1")
        try:
            body = urlopen(f"http://127.0.0.1:{server.server_port}/metrics", timeout=5).read().decode("utf-8")
        finally:
            server.shutdown()
            server.server_close()

        required_metric_names = [
            "cozmo_agent_worker_starts_total",
            "cozmo_agent_jobs_active",
            "cozmo_call_setup_seconds_bucket",
            "cozmo_pipeline_rtt_seconds_bucket",
            "cozmo_perceived_rtt_seconds_bucket",
            "cozmo_stt_latency_seconds_bucket",
            "cozmo_llm_ttft_seconds_bucket",
            "cozmo_tts_first_audio_seconds_bucket",
            "cozmo_worker_job_queue_depth",
            "cozmo_worker_cpu_utilization",
            "cozmo_worker_memory_utilization",
            "cozmo_agent_recoveries_total",
            "cozmo_room_jitter_ms",
            "cozmo_room_packet_loss_pct",
            "cozmo_room_mos_estimate"
        ]

        for metric_name in required_metric_names:
            assert metric_name in body
    finally:
        remove_repo_paths(*inserted_paths)
