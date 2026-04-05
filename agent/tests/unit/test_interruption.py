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


@pytest.mark.unit
def test_interruption_coordinator_cancels_active_response_and_drops_queue() -> None:
    interruption = load_module("agent_interruption", "app/pipeline/interruption.py")
    coordinator = interruption.InterruptionCoordinator()

    coordinator.begin_response()
    assert coordinator.enqueue_output(b"chunk-1") is True
    assert coordinator.enqueue_output(b"chunk-2") is True
    assert coordinator.dequeue_output() == b"chunk-1"

    event = coordinator.interrupt("caller_speech")

    assert event.reason == "caller_speech"
    assert event.dropped_output_count == 1
    assert coordinator.interrupted is True
    assert coordinator.dequeue_output() is None
    assert coordinator.queued_output_count == 0


@pytest.mark.unit
def test_interruption_coordinator_ignores_queueing_after_interrupt() -> None:
    interruption = load_module("agent_interruption", "app/pipeline/interruption.py")
    coordinator = interruption.InterruptionCoordinator()

    coordinator.begin_response()
    coordinator.enqueue_output(b"chunk-1")
    coordinator.interrupt("caller_speech")

    assert coordinator.enqueue_output(b"chunk-2") is False
    coordinator.finish_response()
    assert coordinator.response_active is False
