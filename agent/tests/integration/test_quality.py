from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import SimpleNamespace

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
            or name in {"agent_quality_module", "agent_metrics_quality"}
        ):
            sys.modules.pop(name, None)


def gauge_value(gauge, expected_labels: dict[str, str]) -> float:
    for metric in gauge.collect():
        for sample in metric.samples:
            if sample.name != gauge._name:
                continue
            if sample.labels == expected_labels:
                return sample.value
    return 0.0


class FakeCallStateSink:
    def __init__(self) -> None:
        self.updates = []

    def update_voice_quality(self, room_name, quality):
        self.updates.append((room_name, quality))
        return {"room_name": room_name, "quality": quality}


class FakeRoom:
    async def get_rtc_stats(self):
        return SimpleNamespace(
            publisher_stats=[
                SimpleNamespace(
                    inbound_rtp=SimpleNamespace(
                        jitter=0.012,
                        packets_received=1200,
                        packets_lost=6,
                    ),
                    remote_inbound_rtp=None,
                    candidate_pair=None,
                )
            ],
            subscriber_stats=[
                SimpleNamespace(
                    inbound_rtp=SimpleNamespace(
                        jitter=0.018,
                        packets_received=900,
                        packets_lost=9,
                    ),
                    remote_inbound_rtp=SimpleNamespace(
                        round_trip_time=0.145,
                        fraction_lost=0.01,
                    ),
                    candidate_pair=SimpleNamespace(current_round_trip_time=0.155),
                )
            ],
        )


class FakeProtoRoom:
    async def get_rtc_stats(self):
        return SimpleNamespace(
            publisher_stats=[
                SimpleNamespace(
                    inbound_rtp=SimpleNamespace(
                        received=SimpleNamespace(
                            jitter=0.012,
                            packets_received=1200,
                            packets_lost=6,
                        )
                    )
                )
            ],
            subscriber_stats=[
                SimpleNamespace(
                    inbound_rtp=SimpleNamespace(
                        received=SimpleNamespace(
                            jitter=0.018,
                            packets_received=900,
                            packets_lost=9,
                        )
                    ),
                    remote_inbound_rtp=SimpleNamespace(
                        remote_inbound=SimpleNamespace(
                            round_trip_time=0.145,
                            fraction_lost=0.01,
                        )
                    ),
                    candidate_pair=SimpleNamespace(
                        candidate_pair=SimpleNamespace(current_round_trip_time=0.155)
                    ),
                )
            ],
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_room_quality_monitor_updates_metrics_and_persists_summary() -> None:
    inserted_paths = add_repo_paths()

    try:
        quality_module = load_module("agent_quality_module", "app/observability/quality.py")
        metrics_module = load_module("agent_metrics_quality", "app/observability/metrics.py")

        sink = FakeCallStateSink()
        monitor = quality_module.RoomQualityMonitor(
            room=FakeRoom(),
            worker_name="cozmo-agent-quality",
            agent_config_id="main-inbound",
            room_name="call-+16625640501-quality",
            call_state_sink=sink,
        )

        quality = await monitor.sample_once()

        assert quality is not None
        assert quality.avg_jitter_ms == pytest.approx(15.0)
        assert quality.packet_loss_pct == pytest.approx((15.0 / 2115.0) * 100.0, rel=1e-3)
        assert quality.mos_estimate is not None
        assert sink.updates[0][0] == "call-+16625640501-quality"
        assert gauge_value(
            metrics_module.ROOM_JITTER_MS,
            {"worker_name": "cozmo-agent-quality", "agent_config_id": "main-inbound"},
        ) == pytest.approx(15.0)
        assert gauge_value(
            metrics_module.ROOM_PACKET_LOSS_PCT,
            {"worker_name": "cozmo-agent-quality", "agent_config_id": "main-inbound"},
        ) == pytest.approx((15.0 / 2115.0) * 100.0, rel=1e-3)
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_room_quality_monitor_supports_livekit_proto_stat_wrappers() -> None:
    inserted_paths = add_repo_paths()

    try:
        quality_module = load_module("agent_quality_module_proto", "app/observability/quality.py")
        metrics_module = load_module("agent_metrics_quality_proto", "app/observability/metrics.py")

        sink = FakeCallStateSink()
        monitor = quality_module.RoomQualityMonitor(
            room=FakeProtoRoom(),
            worker_name="cozmo-agent-quality",
            agent_config_id="main-inbound",
            room_name="call-+16625640501-quality",
            call_state_sink=sink,
        )

        quality = await monitor.sample_once()

        assert quality is not None
        assert quality.avg_jitter_ms == pytest.approx(15.0)
        assert quality.packet_loss_pct == pytest.approx((15.0 / 2115.0) * 100.0, rel=1e-3)
        assert quality.mos_estimate is not None
        assert sink.updates[0][0] == "call-+16625640501-quality"
        assert gauge_value(
            metrics_module.ROOM_MOS_ESTIMATE,
            {"worker_name": "cozmo-agent-quality", "agent_config_id": "main-inbound"},
        ) == pytest.approx(quality.mos_estimate)
    finally:
        remove_repo_paths(*inserted_paths)
