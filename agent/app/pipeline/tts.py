"""Deterministic greeting-audio helpers for the worker."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class RenderedAudio:
    """Small PCM payload ready to be published through LiveKit."""

    transcript_text: str
    pcm16le: bytes
    sample_rate: int = 24_000
    num_channels: int = 1
    frame_duration_ms: int = 20

    @property
    def samples_per_frame(self) -> int:
        """Return the per-channel sample count for one frame chunk."""

        return int(self.sample_rate * self.frame_duration_ms / 1000)

    def iter_pcm_frames(self) -> list[bytes]:
        """Split the PCM payload into fixed-size frame-aligned chunks."""

        bytes_per_frame = self.samples_per_frame * self.num_channels * 2
        frames: list[bytes] = []
        for offset in range(0, len(self.pcm16le), bytes_per_frame):
            frame = self.pcm16le[offset : offset + bytes_per_frame]
            if len(frame) < bytes_per_frame:
                frame = frame + (b"\x00" * (bytes_per_frame - len(frame)))
            frames.append(frame)
        return frames


def build_initial_greeting(agent_name: str) -> str:
    """Build the first-turn greeting text from the resolved agent config."""

    normalized = " ".join(str(agent_name or "").split()).strip() or "Cozmo"
    return f"Hello, you've reached {normalized}. How can I help you today?"


def _render_tone_segment(
    *,
    frequency_hz: float,
    duration_ms: int,
    sample_rate: int,
    amplitude: float = 0.20,
) -> bytes:
    """Render a short sine-wave segment as mono PCM16LE."""

    total_samples = int(sample_rate * duration_ms / 1000)
    pcm = bytearray()
    fade_samples = min(max(total_samples // 10, 1), sample_rate // 200)

    for index in range(total_samples):
        envelope = 1.0
        if index < fade_samples:
            envelope = index / fade_samples
        elif total_samples - index <= fade_samples:
            envelope = max(total_samples - index, 0) / fade_samples

        sample = amplitude * envelope * math.sin((2.0 * math.pi * frequency_hz * index) / sample_rate)
        value = max(-32767, min(32767, int(sample * 32767)))
        pcm.extend(int(value).to_bytes(2, byteorder="little", signed=True))

    return bytes(pcm)


def _render_silence(*, duration_ms: int, sample_rate: int, num_channels: int = 1) -> bytes:
    """Render zero-valued PCM for a short silence interval."""

    total_samples = int(sample_rate * duration_ms / 1000)
    return b"\x00\x00" * total_samples * num_channels


class TtsAdapter:
    """Deterministic placeholder renderer used until provider TTS is implemented."""

    def __init__(
        self,
        *,
        sample_rate: int = 24_000,
        num_channels: int = 1,
        frame_duration_ms: int = 20,
    ) -> None:
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.frame_duration_ms = frame_duration_ms

    def synthesize(self, text: str) -> RenderedAudio:
        """Render a short audible greeting placeholder for the supplied text."""

        pcm = b"".join(
            (
                _render_silence(duration_ms=120, sample_rate=self.sample_rate, num_channels=self.num_channels),
                _render_tone_segment(frequency_hz=660.0, duration_ms=220, sample_rate=self.sample_rate),
                _render_silence(duration_ms=50, sample_rate=self.sample_rate, num_channels=self.num_channels),
                _render_tone_segment(frequency_hz=880.0, duration_ms=240, sample_rate=self.sample_rate),
                _render_silence(duration_ms=120, sample_rate=self.sample_rate, num_channels=self.num_channels),
            )
        )
        return RenderedAudio(
            transcript_text=text,
            pcm16le=pcm,
            sample_rate=self.sample_rate,
            num_channels=self.num_channels,
            frame_duration_ms=self.frame_duration_ms,
        )
