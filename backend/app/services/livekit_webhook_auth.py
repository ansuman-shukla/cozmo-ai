"""Verification helpers for signed LiveKit webhook requests."""

from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import timedelta
import hashlib
from typing import Any

from livekit.api import TokenVerifier


class LiveKitWebhookAuthError(ValueError):
    """Raised when a LiveKit webhook request fails authentication."""


def _extract_bearer_token(authorization: str | None) -> str:
    """Normalize a raw or Bearer-prefixed Authorization header value."""

    value = str(authorization or "").strip()
    if not value:
        raise LiveKitWebhookAuthError("Missing Authorization header")

    parts = value.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    if len(parts) == 1:
        return parts[0]
    raise LiveKitWebhookAuthError("Malformed Authorization header")


@dataclass(slots=True, frozen=True)
class LiveKitWebhookVerifier:
    """Verify the JWT signature and body checksum on LiveKit webhooks."""

    api_key: str
    api_secret: str
    leeway_seconds: int = 60

    @classmethod
    def from_settings(cls, settings: Any) -> "LiveKitWebhookVerifier":
        """Build a verifier from the backend settings object."""

        return cls(
            api_key=str(getattr(settings, "livekit_api_key", "") or ""),
            api_secret=str(getattr(settings, "livekit_api_secret", "") or ""),
        )

    def verify(self, *, body: bytes, authorization: str | None) -> dict[str, Any]:
        """Validate a LiveKit webhook token against the raw request body."""

        if not self.api_key or not self.api_secret:
            raise LiveKitWebhookAuthError("LiveKit webhook verification is not configured")

        token = _extract_bearer_token(authorization)
        try:
            claims = TokenVerifier(
                api_key=self.api_key,
                api_secret=self.api_secret,
                leeway=timedelta(seconds=self.leeway_seconds),
            ).verify(token)
        except Exception as exc:
            raise LiveKitWebhookAuthError("Invalid LiveKit webhook signature") from exc

        expected_hash = b64encode(hashlib.sha256(body).digest()).decode("ascii")
        provided_hash = str(getattr(claims, "sha256", "") or "").strip()
        if not provided_hash:
            raise LiveKitWebhookAuthError("Missing LiveKit webhook body hash")
        try:
            provided_hash_bytes = b64decode(provided_hash, validate=True)
        except ValueError as exc:
            raise LiveKitWebhookAuthError("Malformed LiveKit webhook body hash") from exc
        if provided_hash_bytes != hashlib.sha256(body).digest():
            raise LiveKitWebhookAuthError("LiveKit webhook body hash mismatch")

        return {
            "iss": self.api_key,
            "sha256": expected_hash,
        }
