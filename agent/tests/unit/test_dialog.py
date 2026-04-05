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
    sys.modules[module_name] = module
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
            or name in {"agent_objection_dialog", "agent_transfer_dialog", "agent_fallback_dialog"}
        ):
            sys.modules.pop(name, None)


@pytest.mark.unit
def test_objection_classifier_routes_scripted_llm_and_transfer() -> None:
    inserted_paths = add_repo_paths()

    try:
        objections = load_module("agent_objection_dialog", "app/dialog/objection_handler.py")
        handler = objections.ObjectionHandler()

        scripted = handler.classify("I don't believe this is real.")
        llm = handler.classify("Can you explain the pricing tiers?")
        transfer = handler.classify(
            "I want to speak to a human representative.",
            escalation_triggers=("human", "manager"),
        )

        assert scripted.route == objections.ObjectionRoute.SCRIPTED
        assert scripted.objection_type == "trust"
        assert scripted.scripted_response
        assert llm.route == objections.ObjectionRoute.LLM
        assert transfer.route == objections.ObjectionRoute.TRANSFER
        assert transfer.objection_type == "handoff_request"
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
def test_no_answer_fallback_is_selected_when_retrieval_misses() -> None:
    inserted_paths = add_repo_paths()

    try:
        fallbacks = load_module("agent_fallback_dialog", "app/dialog/fallbacks.py")
        from cozmo_contracts.runtime import AgentRuntimeConfig

        runtime_config = AgentRuntimeConfig(
            config_id="main-inbound",
            did="+16625640501",
            agent_name="Main Reception",
            persona_prompt="Be concise and grounded.",
            kb_collection="main-faq",
            llm_provider="gemini",
            llm_model="gemini-3-flash-preview",
            tts_provider="deepgram",
            tts_model="aura-2-thalia-en",
            tts_voice="thalia",
            escalation_triggers=["human"],
        )

        assert fallbacks.should_use_no_answer_fallback([]) is True
        assert "grounded information" in fallbacks.build_no_answer_response(runtime_config)
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
def test_transfer_request_builder_builds_expected_payload() -> None:
    inserted_paths = add_repo_paths()

    try:
        transfers = load_module("agent_transfer_dialog", "app/dialog/transfer.py")
        from cozmo_contracts.runtime import AgentRuntimeConfig

        runtime_config = AgentRuntimeConfig(
            config_id="main-inbound",
            did="+16625640501",
            agent_name="Main Reception",
            persona_prompt="Be concise and grounded.",
            kb_collection="main-faq",
            llm_provider="gemini",
            llm_model="gemini-3-flash-preview",
            tts_provider="deepgram",
            tts_model="aura-2-thalia-en",
            tts_voice="thalia",
            escalation_triggers=["human"],
                transfer_target="sip:frontdesk@pbx.example.com",
        )
        builder = transfers.TransferRequestBuilder()

        request = builder.build(
            runtime_config=runtime_config,
            room_name="call-+16625640501-a1b2",
            reason="Caller asked for a human",
            provider_call_id="CA123",
            ani="+919262561716",
        )

        assert request.room_name == "call-+16625640501-a1b2"
        assert request.agent_config_id == "main-inbound"
        assert request.transfer_target == "sip:frontdesk@pbx.example.com"
        assert request.reason == "Caller asked for a human"
        assert request.provider_call_id == "CA123"
        assert request.did == "+16625640501"
        assert request.ani == "+919262561716"
    finally:
        remove_repo_paths(*inserted_paths)
