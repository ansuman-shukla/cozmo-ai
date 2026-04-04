from importlib.util import module_from_spec, spec_from_file_location
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


@pytest.mark.integration
def test_parse_sip_attributes() -> None:
    telephony = load_module("agent_telephony", "app/telephony.py")
    context = telephony.parse_sip_attributes(
        {
            "sip.phoneNumber": "+15551234567",
            "sip.trunkPhoneNumber": "+15559876543",
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
    assert context.room_name == "call-123"
    assert context.provider_call_id == "CA123"
    assert context.livekit_call_id == "lk-call-1"
    assert context.call_status == "active"
