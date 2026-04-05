"""Speech-to-text adapter helpers."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any


class SttAdapterError(RuntimeError):
    """Raised when the configured STT provider cannot be initialized."""


@dataclass(slots=True)
class SttAdapter:
    """Thin provider wrapper for worker STT initialization."""

    provider: str
    model: str
    api_key: str | None = None

    @classmethod
    def from_settings(cls, settings: Any) -> "SttAdapter":
        """Build an STT adapter from the shared worker settings."""

        return cls(
            provider=str(settings.stt_provider),
            model=str(settings.stt_model),
            api_key=getattr(settings, "deepgram_api_key", None),
        )

    def create_provider(self) -> Any:
        """Create the configured provider plugin object."""

        if self.provider != "deepgram":
            raise SttAdapterError(f"Unsupported STT provider: {self.provider}")

        try:
            deepgram = importlib.import_module("livekit.plugins.deepgram")
        except ImportError as exc:
            raise SttAdapterError(
                "Deepgram LiveKit plugin is not installed; run `uv sync --all-packages --dev`."
            ) from exc

        kwargs: dict[str, Any] = {"model": self.model}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        return deepgram.STT(**kwargs)
