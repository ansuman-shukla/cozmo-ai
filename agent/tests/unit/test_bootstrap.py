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
    agent_root = str(Path(__file__).resolve().parents[2])
    contracts_root = str(Path(__file__).resolve().parents[3] / "contracts")
    sys.path.insert(0, agent_root)
    sys.path.insert(0, contracts_root)
    return agent_root, contracts_root


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


class FakeRepository:
    def __init__(self, mapping):
        self.mapping = mapping

    def get_by_did(self, did: str):
        return self.mapping.get(did)


@pytest.mark.unit
def test_resolve_call_context_loads_matching_agent_config() -> None:
    inserted_paths = add_repo_paths()

    try:
        bootstrap = load_module("agent_bootstrap", "app/bootstrap.py")
        from cozmo_contracts.models import AgentConfigRecord

        config = AgentConfigRecord(
            config_id="sales-main",
            did="+15559876543",
            agent_name="Sales Agent",
            persona_prompt="Help the caller with pricing.",
            kb_collection="sales-faq",
            llm_provider="openai",
            llm_model="gpt-realtime-mini",
            tts_provider="deepgram",
            tts_model="aura-2-thalia-en",
            tts_voice="thalia",
            escalation_triggers=["human"],
            updated_at=datetime.now(UTC),
        )

        resolved = bootstrap.resolve_call_context(
            repository=FakeRepository({"+15559876543": config}),
            room_name="call-+16625640501-a1b2",
            participant_attributes={
                "sip.trunkPhoneNumber": "+15559876543",
                "sip.phoneNumber": "+15551234567",
                "sip.twilio.callSid": "CA123",
            },
            participant_identity="sip-caller-1",
            participant_kind="SIP",
        )

        assert resolved.did == "+15559876543"
        assert resolved.ani == "+15551234567"
        assert resolved.provider_call_id == "CA123"
        assert resolved.agent_config.config_id == "sales-main"
        assert resolved.participant_attributes()["cozmo.agent_config_id"] == "sales-main"
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
def test_resolve_call_context_rejects_unknown_did() -> None:
    inserted_paths = add_repo_paths()

    try:
        bootstrap = load_module("agent_bootstrap", "app/bootstrap.py")

        with pytest.raises(bootstrap.AgentBootstrapError):
            bootstrap.resolve_call_context(
                repository=FakeRepository({}),
                room_name="call-+16625640501-a1b2",
                participant_attributes={
                    "sip.trunkPhoneNumber": "+15550001111",
                    "sip.phoneNumber": "+15551234567",
                },
            )
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
def test_room_name_matches_prefix_and_identity_builder() -> None:
    inserted_paths = add_repo_paths()

    try:
        bootstrap = load_module("agent_bootstrap", "app/bootstrap.py")

        assert bootstrap.room_name_matches_prefix("call-+16625640501-a1b2", "call-") is True
        assert bootstrap.room_name_matches_prefix("demo-room", "call-") is False
        assert (
            bootstrap.build_agent_identity("cozmo-agent-1", "call-+16625640501-a1b2")
            == "cozmo-agent-1-call--16625640501-a1b2"
        )
    finally:
        remove_repo_paths(*inserted_paths)
