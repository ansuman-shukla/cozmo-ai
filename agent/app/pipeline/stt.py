"""Speech-to-text adapter placeholder."""


class SttAdapter:
    """Stub adapter for STT integration."""

    def transcribe(self, audio_chunk: bytes) -> str:
        return audio_chunk.decode("utf-8", errors="ignore")

