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
def test_vad_emits_speech_started_and_ended_events() -> None:
    vad_module = load_module("agent_vad_pipeline", "app/pipeline/vad.py")
    detector = vad_module.VadAdapter(
        energy_threshold=0.5,
        start_trigger_frames=2,
        end_trigger_frames=3,
        frame_duration_ms=20,
    )

    started = []
    for energy in (0.1, 0.7, 0.8):
        started.extend(
            detector.detect_events(
                vad_module.AudioFrameAssessment(
                    is_speech=energy >= 0.5,
                    energy=energy,
                    duration_ms=20,
                )
            )
        )

    assert [event.type for event in started] == [vad_module.TurnEventType.SPEECH_STARTED]
    assert started[0].speech_ms == 40

    ended = []
    for energy in (0.1, 0.1, 0.1):
        ended.extend(
            detector.detect_events(
                vad_module.AudioFrameAssessment(
                    is_speech=False,
                    energy=energy,
                    duration_ms=20,
                )
            )
        )

    assert [event.type for event in ended] == [vad_module.TurnEventType.SPEECH_ENDED]
    assert ended[0].silence_ms == 60
    assert detector.in_speech is False


@pytest.mark.unit
def test_vad_assess_uses_pcm_rms_for_raw_frames() -> None:
    vad_module = load_module("agent_vad_pipeline", "app/pipeline/vad.py")
    detector = vad_module.VadAdapter(energy_threshold=0.01)

    silence = detector.assess(b"\x00\x00" * 160)
    speech = detector.assess((5000).to_bytes(2, "little", signed=True) * 160)

    assert silence.is_speech is False
    assert speech.is_speech is True
    assert speech.energy > silence.energy
