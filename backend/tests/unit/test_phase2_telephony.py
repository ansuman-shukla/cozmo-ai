from datetime import UTC, datetime
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
    spec.loader.exec_module(module)
    return module


def add_repo_paths() -> tuple[str, str]:
    backend_root = str(Path(__file__).resolve().parents[2])
    contracts_root = str(Path(__file__).resolve().parents[3] / "contracts")
    sys.path.insert(0, backend_root)
    sys.path.insert(0, contracts_root)
    return backend_root, contracts_root


def remove_repo_paths(*paths: str) -> None:
    for path in paths:
        if path in sys.path:
            sys.path.remove(path)
    for name in list(sys.modules):
        if (
            name == "app"
            or name.startswith("app.")
            or name == "cozmo_contracts"
            or name.startswith("cozmo_contracts.")
        ):
            sys.modules.pop(name, None)


@pytest.mark.unit
def test_parse_sip_attributes_maps_inbound_did_and_ani() -> None:
    telephony = load_module("backend_telephony", "app/services/telephony.py")
    context = telephony.parse_sip_attributes(
        {
            "sip.trunkPhoneNumber": "+15559876543",
            "sip.phoneNumber": "+15551234567",
            "sip.twilio.callSid": "CA123",
            "sip.callID": "lk-call-1",
            "sip.callStatus": "active",
        },
        room_name="call-123",
        participant_identity="sip-caller-1",
        participant_kind="SIP",
    )

    assert context.did == "+15559876543"
    assert context.ani == "+15551234567"
    assert context.provider_call_id == "CA123"
    assert context.livekit_call_id == "lk-call-1"
    assert context.call_status == "active"


@pytest.mark.unit
def test_twilio_event_id_is_stable_for_duplicate_payloads() -> None:
    inserted_paths = add_repo_paths()

    try:
        webhook_ingestion = load_module("webhook_ingestion", "app/services/webhook_ingestion.py")
        payload = {
            "CallSid": "CA123",
            "CallStatus": "completed",
            "Timestamp": "Sun, 24 Aug 2025 16:00:00 +0000",
            "CallDuration": "42",
            "From": "+15551234567",
            "To": "+15559876543",
        }

        assert (
            webhook_ingestion.build_twilio_event_id(payload)
            == webhook_ingestion.build_twilio_event_id(payload)
        )
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
def test_parse_livekit_timestamp_uses_unix_seconds() -> None:
    inserted_paths = add_repo_paths()

    try:
        webhook_ingestion = load_module("webhook_ingestion", "app/services/webhook_ingestion.py")
        timestamp = webhook_ingestion.parse_livekit_timestamp(1_710_000_000)

        assert timestamp == datetime.fromtimestamp(1_710_000_000, UTC)
    finally:
        remove_repo_paths(*inserted_paths)
