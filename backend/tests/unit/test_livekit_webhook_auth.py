from base64 import b64encode, urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
import hashlib
import hmac
import json
from pathlib import Path

import pytest


def load_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[2] / relative_path
    spec = spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def encode_segment(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def build_livekit_token(
    *,
    body: bytes,
    api_key: str,
    api_secret: str,
    now: datetime,
    expires_in_seconds: int = 300,
) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": api_key,
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp()),
        "sha256": b64encode(hashlib.sha256(body).digest()).decode("ascii"),
    }
    header_segment = encode_segment(header)
    payload_segment = encode_segment(payload)
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature = hmac.new(api_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_segment = urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"Bearer {header_segment}.{payload_segment}.{signature_segment}"


@pytest.mark.unit
def test_verify_accepts_valid_livekit_webhook_token() -> None:
    module = load_module("livekit_webhook_auth", "app/services/livekit_webhook_auth.py")
    body = b'{"event":"room_started","id":"evt-1"}'
    now = datetime.now(UTC)
    verifier = module.LiveKitWebhookVerifier(api_key="testkey", api_secret="testsecret")
    token = build_livekit_token(
        body=body,
        api_key="testkey",
        api_secret="testsecret",
        now=now,
    )

    claims = verifier.verify(body=body, authorization=token)

    assert claims["iss"] == "testkey"


@pytest.mark.unit
def test_verify_rejects_body_hash_mismatch() -> None:
    module = load_module("livekit_webhook_auth", "app/services/livekit_webhook_auth.py")
    now = datetime.now(UTC)
    verifier = module.LiveKitWebhookVerifier(api_key="testkey", api_secret="testsecret")
    token = build_livekit_token(
        body=b'{"event":"room_started","id":"evt-1"}',
        api_key="testkey",
        api_secret="testsecret",
        now=now,
    )

    with pytest.raises(module.LiveKitWebhookAuthError):
        verifier.verify(
            body=b'{"event":"room_started","id":"evt-2"}',
            authorization=token,
        )


@pytest.mark.unit
def test_verify_accepts_small_clock_skew() -> None:
    module = load_module("livekit_webhook_auth", "app/services/livekit_webhook_auth.py")
    body = b'{"event":"room_started","id":"evt-1"}'
    now = datetime.now(UTC)
    verifier = module.LiveKitWebhookVerifier(api_key="testkey", api_secret="testsecret")
    token = build_livekit_token(
        body=body,
        api_key="testkey",
        api_secret="testsecret",
        now=now + timedelta(seconds=30),
    )

    claims = verifier.verify(body=body, authorization=token)

    assert claims["iss"] == "testkey"
