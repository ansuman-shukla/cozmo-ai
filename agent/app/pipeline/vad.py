"""Voice-activity and turn-detection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import sqrt


class TurnEventType(str, Enum):
    """Discrete speech-boundary events emitted by the turn detector."""

    SPEECH_STARTED = "speech_started"
    SPEECH_ENDED = "speech_ended"


@dataclass(frozen=True, slots=True)
class AudioFrameAssessment:
    """Normalized per-frame speech assessment."""

    is_speech: bool
    energy: float
    duration_ms: int = 20


@dataclass(frozen=True, slots=True)
class TurnDetectionEvent:
    """A detected conversational boundary event."""

    type: TurnEventType
    frame_index: int
    timestamp_ms: int
    energy: float
    speech_ms: int
    silence_ms: int


class VadAdapter:
    """Stateful wrapper around frame-level VAD decisions."""

    def __init__(
        self,
        *,
        energy_threshold: float = 0.015,
        start_trigger_frames: int = 2,
        end_trigger_frames: int = 4,
        frame_duration_ms: int = 20,
    ) -> None:
        self.energy_threshold = energy_threshold
        self.start_trigger_frames = start_trigger_frames
        self.end_trigger_frames = end_trigger_frames
        self.frame_duration_ms = frame_duration_ms
        self.reset()

    @property
    def in_speech(self) -> bool:
        """Return whether the detector currently considers the caller to be in a turn."""

        return self._in_speech

    def reset(self) -> None:
        """Reset the detector state for a new stream or call."""

        self._in_speech = False
        self._frame_index = 0
        self._timestamp_ms = 0
        self._speech_run_frames = 0
        self._silence_run_frames = 0
        self._speech_ms = 0

    def assess(self, audio_frame: bytes | AudioFrameAssessment) -> AudioFrameAssessment:
        """Normalize raw PCM or a precomputed decision into an assessment object."""

        if isinstance(audio_frame, AudioFrameAssessment):
            return audio_frame

        energy = self._pcm16le_rms(audio_frame)
        return AudioFrameAssessment(
            is_speech=energy >= self.energy_threshold,
            energy=energy,
            duration_ms=self.frame_duration_ms,
        )

    def detect_events(self, audio_frame: bytes | AudioFrameAssessment) -> list[TurnDetectionEvent]:
        """Feed one frame and emit zero or more speech-boundary events."""

        assessment = self.assess(audio_frame)
        self._frame_index += 1
        self._timestamp_ms += assessment.duration_ms

        if assessment.is_speech:
            self._speech_run_frames += 1
            self._silence_run_frames = 0
            if self._in_speech:
                self._speech_ms += assessment.duration_ms
            if not self._in_speech and self._speech_run_frames >= self.start_trigger_frames:
                self._in_speech = True
                self._speech_ms = self._speech_run_frames * assessment.duration_ms
                return [
                    TurnDetectionEvent(
                        type=TurnEventType.SPEECH_STARTED,
                        frame_index=self._frame_index,
                        timestamp_ms=self._timestamp_ms,
                        energy=assessment.energy,
                        speech_ms=self._speech_ms,
                        silence_ms=0,
                    )
                ]
            return []

        if not self._in_speech:
            self._speech_run_frames = 0
            return []

        self._silence_run_frames += 1
        if self._silence_run_frames >= self.end_trigger_frames:
            silence_ms = self._silence_run_frames * assessment.duration_ms
            event = TurnDetectionEvent(
                type=TurnEventType.SPEECH_ENDED,
                frame_index=self._frame_index,
                timestamp_ms=self._timestamp_ms,
                energy=assessment.energy,
                speech_ms=self._speech_ms,
                silence_ms=silence_ms,
            )
            self._in_speech = False
            self._speech_run_frames = 0
            self._silence_run_frames = 0
            self._speech_ms = 0
            return [event]

        return []

    @staticmethod
    def _pcm16le_rms(audio_frame: bytes) -> float:
        """Compute a normalized RMS amplitude for mono or interleaved PCM16LE bytes."""

        if not audio_frame:
            return 0.0

        sample_count = len(audio_frame) // 2
        if sample_count == 0:
            return 0.0

        total = 0.0
        for offset in range(0, len(audio_frame) - 1, 2):
            sample = int.from_bytes(audio_frame[offset : offset + 2], byteorder="little", signed=True)
            normalized = sample / 32768.0
            total += normalized * normalized

        return sqrt(total / sample_count)
