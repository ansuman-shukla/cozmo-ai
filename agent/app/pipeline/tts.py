"""Deterministic greeting-audio helpers for the worker."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import math
import re
from typing import Any


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


class TtsAdapterError(RuntimeError):
    """Raised when the configured TTS provider cannot be initialized."""


@dataclass(frozen=True, slots=True)
class TtsChunk:
    """A stable text chunk ready for provider TTS synthesis."""

    index: int
    text: str


class TtsChunker:
    """Split agent text into stable sentence-oriented chunks for TTS."""

    def __init__(self, *, max_chars: int = 180) -> None:
        self.max_chars = max_chars

    def chunk(self, text: str) -> list[TtsChunk]:
        """Split text into sentence-aware chunks capped by `max_chars`."""

        normalized = " ".join(str(text or "").split()).strip()
        if not normalized:
            return []

        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", normalized)
            if sentence.strip()
        ]
        if not sentences:
            sentences = [normalized]

        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            if len(sentence) > self.max_chars:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(self._chunk_long_sentence(sentence))
                continue

            candidate = sentence if not current else f"{current} {sentence}"
            if current and len(candidate) > self.max_chars:
                chunks.append(current)
                current = sentence
            else:
                current = candidate

        if current:
            chunks.append(current)

        return [TtsChunk(index=index, text=chunk) for index, chunk in enumerate(chunks)]

    def _chunk_long_sentence(self, sentence: str) -> list[str]:
        """Split a long sentence by words while preserving stable chunk ordering."""

        words = sentence.split()
        chunks: list[str] = []
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if current and len(candidate) > self.max_chars:
                chunks.append(current)
                current = word
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks


class PlaceholderGreetingRenderer:
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


@dataclass(slots=True)
class TtsAdapter:
    """Thin provider wrapper for worker TTS initialization."""

    provider: str
    model: str
    voice: str | None = None
    api_key: str | None = None

    @classmethod
    def from_settings(cls, settings: Any) -> "TtsAdapter":
        """Build a provider-backed TTS adapter from the shared worker settings."""

        return cls(
            provider=str(settings.tts_provider),
            model=str(settings.tts_model),
            voice=getattr(settings, "tts_voice", None),
            api_key=getattr(settings, "deepgram_api_key", None),
        )

    def create_provider(self) -> Any:
        """Create the configured provider plugin object."""

        if self.provider != "deepgram":
            raise TtsAdapterError(f"Unsupported TTS provider: {self.provider}")

        try:
            deepgram = importlib.import_module("livekit.plugins.deepgram")
        except ImportError as exc:
            raise TtsAdapterError(
                "Deepgram LiveKit plugin is not installed; run `uv sync --all-packages --dev`."
            ) from exc

        constructor = deepgram.TTS
        base_kwargs: dict[str, Any] = {"model": self.model}
        if self.api_key:
            base_kwargs["api_key"] = self.api_key

        if self.voice:
            try:
                return constructor(voice=self.voice, **base_kwargs)
            except TypeError:
                pass
        return constructor(**base_kwargs)
