"""Voice activity detection adapter placeholder."""


class VadAdapter:
    """Stub adapter for VAD integration."""

    def detect_turn(self, audio_frame: bytes) -> bool:
        return bool(audio_frame)

