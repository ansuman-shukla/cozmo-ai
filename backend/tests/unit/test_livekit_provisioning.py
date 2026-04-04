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
        if name == "cozmo_contracts" or name.startswith("cozmo_contracts."):
            sys.modules.pop(name, None)


@pytest.mark.unit
def test_build_inbound_trunk_payload_matches_livekit_shape() -> None:
    inserted_paths = add_repo_paths()

    try:
        livekit_service = load_module("livekit_service", "app/services/livekit_service.py")
        service = livekit_service.LiveKitService(
            base_url="wss://project.livekit.cloud",
            sip_trunk_id="trunk-123",
        )

        payload = service.build_inbound_trunk_payload(
            trunk_name="cozmo-inbound",
            phone_numbers=["+15551234567"],
            allowed_addresses=["54.172.60.0/24"],
            allowed_numbers=["+15551234567"],
            metadata='{"provider":"twilio"}',
        )

        assert payload == {
            "name": "cozmo-inbound",
            "numbers": ["+15551234567"],
            "metadata": '{"provider":"twilio"}',
            "allowedAddresses": ["54.172.60.0/24"],
            "allowedNumbers": ["+15551234567"],
            "krispEnabled": True,
        }
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
def test_build_dispatch_rule_payload_includes_agent_dispatch_and_room_prefix() -> None:
    inserted_paths = add_repo_paths()

    try:
        livekit_service = load_module("livekit_service", "app/services/livekit_service.py")
        service = livekit_service.LiveKitService(
            base_url="wss://project.livekit.cloud",
            sip_trunk_id="trunk-123",
            dispatch_rule_name="cozmo-pstn",
            dispatch_agent_name="inbound-agent",
            room_prefix="call-",
        )

        payload = service.build_dispatch_rule_payload(
            trunk_ids=["trunk-123"],
            participant_attributes={"cozmo.route": "sales"},
            metadata="dispatch metadata",
            agent_metadata='{"source":"pstn"}',
        )

        assert payload == {
            "name": "cozmo-pstn",
            "rule": {
                "dispatchRuleIndividual": {
                    "roomPrefix": "call-",
                }
            },
            "trunkIds": ["trunk-123"],
            "roomConfig": {
                "agents": [
                    {
                        "agentName": "inbound-agent",
                        "metadata": '{"source":"pstn"}',
                    }
                ]
            },
            "attributes": {"cozmo.route": "sales"},
            "metadata": "dispatch metadata",
        }
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
def test_validation_report_flags_missing_livekit_trunk_configuration() -> None:
    inserted_paths = add_repo_paths()

    try:
        livekit_service = load_module("livekit_service", "app/services/livekit_service.py")
        service = livekit_service.LiveKitService(base_url="ws://localhost:7880", sip_trunk_id=None)

        report = service.validation_report()

        assert report.ready is False
        assert "LIVEKIT_SIP_TRUNK_ID" in report.missing
        assert report.warnings == ()
    finally:
        remove_repo_paths(*inserted_paths)
