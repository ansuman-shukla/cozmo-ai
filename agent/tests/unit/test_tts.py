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
def test_build_initial_greeting_normalizes_agent_name() -> None:
    tts = load_module("agent_tts", "app/pipeline/tts.py")

    greeting = tts.build_initial_greeting("  Sales   Agent  ")

    assert greeting == "Hello, you've reached Sales Agent. How can I help you today?"


@pytest.mark.unit
def test_tts_adapter_synthesize_returns_pcm_audio() -> None:
    tts = load_module("agent_tts", "app/pipeline/tts.py")
    adapter = tts.PlaceholderGreetingRenderer()

    rendered = adapter.synthesize("Hello there.")

    assert rendered.transcript_text == "Hello there."
    assert rendered.sample_rate == 24_000
    assert rendered.num_channels == 1
    assert rendered.samples_per_frame == 480
    assert len(rendered.pcm16le) > 0
    assert len(rendered.pcm16le) % 2 == 0


@pytest.mark.unit
def test_rendered_audio_frames_are_fixed_size() -> None:
    tts = load_module("agent_tts", "app/pipeline/tts.py")
    rendered = tts.RenderedAudio(
        transcript_text="hello",
        pcm16le=b"\x01\x02" * 15,
        sample_rate=1000,
        num_channels=1,
        frame_duration_ms=10,
    )

    frames = rendered.iter_pcm_frames()

    assert len(frames) == 2
    assert all(len(frame) == 20 for frame in frames)
    assert frames[-1][-10:] == b"\x00\x00" * 5


@pytest.mark.unit
def test_tts_chunker_emits_stable_sentence_chunks() -> None:
    tts = load_module("agent_tts", "app/pipeline/tts.py")
    chunker = tts.TtsChunker(max_chars=60)

    chunks = chunker.chunk(
        "Thanks for calling. I can help with pricing and setup questions. "
        "If you need a person, I can escalate that too."
    )

    assert [chunk.text for chunk in chunks] == [
        "Thanks for calling.",
        "I can help with pricing and setup questions.",
        "If you need a person, I can escalate that too.",
    ]
