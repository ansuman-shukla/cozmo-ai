from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from .support import (
    FakeAgentConfigRepository,
    FakeCallSessionRepository,
    FakeMongoResources,
    FakeTranscriptRepository,
    add_repo_paths,
    build_mongo_factory,
    build_settings,
    remove_repo_paths,
)


@pytest.mark.integration
def test_backend_startup_initializes_indexes(monkeypatch: pytest.MonkeyPatch) -> None:
    inserted_paths = add_repo_paths()

    try:
        from app import main as main_module

        fake_resources = FakeMongoResources(
            call_sessions=FakeCallSessionRepository([]),
            transcripts=FakeTranscriptRepository([]),
            agent_configs=FakeAgentConfigRepository([]),
        )
        monkeypatch.setattr(main_module, "get_settings", lambda: build_settings())
        monkeypatch.setattr(main_module, "MongoResources", build_mongo_factory(fake_resources))

        app = main_module.create_app()

        with TestClient(app) as client:
            response = client.get("/ready")
            assert response.status_code == 200
            assert response.json() == {"status": "ready"}

        assert fake_resources.ensure_indexes_called is True
        assert fake_resources.closed is True
        assert fake_resources.connection_args == {
            "mongo_uri": "mongodb+srv://user:pass@cluster.example.mongodb.net/cozmo_voice",
            "database_name": "cozmo_voice",
            "server_selection_timeout_ms": 2500,
        }
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
def test_backend_readiness_degrades_when_mongo_initialization_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inserted_paths = add_repo_paths()

    try:
        from app import main as main_module

        class FailingMongoResources:
            @classmethod
            def from_connection_string(cls, *args, **kwargs):
                raise RuntimeError("MongoDB unavailable")

        monkeypatch.setattr(main_module, "get_settings", lambda: build_settings())
        monkeypatch.setattr(main_module, "MongoResources", FailingMongoResources)

        app = main_module.create_app()
        with TestClient(app) as client:
            response = client.get("/ready")
            assert response.status_code == 503
            assert response.json() == {"status": "degraded", "mongo": "unavailable"}
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
def test_calls_and_agents_routes_read_from_repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inserted_paths = add_repo_paths()

    try:
        from app import main as main_module
        from cozmo_contracts.models import AgentConfigRecord, CallSessionRecord, CallSessionStatus, TranscriptTurn

        now = datetime.now(UTC)
        fake_resources = FakeMongoResources(
            call_sessions=FakeCallSessionRepository(
                [
                    CallSessionRecord(
                        provider="twilio",
                        provider_call_id="CA100",
                        room_name="call-100",
                        did="+15551234567",
                        ani="+15550000001",
                        agent_config_id="sales-main",
                        status=CallSessionStatus.ACTIVE,
                        created_at=now,
                    ),
                    CallSessionRecord(
                        provider="twilio",
                        provider_call_id="CA200",
                        room_name="call-200",
                        did="+15557654321",
                        ani="+15550000002",
                        agent_config_id="support-main",
                        status=CallSessionStatus.COMPLETED,
                        created_at=now - timedelta(minutes=5),
                    ),
                ]
            ),
            transcripts=FakeTranscriptRepository(
                [
                    TranscriptTurn(
                        room_name="call-100",
                        turn_index=1,
                        speaker="agent",
                        text="How can I help?",
                        timestamp=now,
                    ),
                    TranscriptTurn(
                        room_name="call-100",
                        turn_index=0,
                        speaker="user",
                        text="I need pricing details.",
                        timestamp=now - timedelta(seconds=5),
                    ),
                ]
            ),
            agent_configs=FakeAgentConfigRepository(
                [
                    AgentConfigRecord(
                        config_id="sales-main",
                        did="+15551234567",
                        agent_name="Sales Agent",
                        persona_prompt="Help with pricing and plan selection.",
                        kb_collection="sales-faq",
                        llm_provider="openai",
                        llm_model="gpt-realtime-mini",
                        tts_provider="deepgram",
                        tts_model="aura-2-thalia-en",
                        tts_voice="thalia",
                        escalation_triggers=["human"],
                        transfer_target="sip:sales@example.com",
                        active=True,
                        updated_at=now,
                    ),
                    AgentConfigRecord(
                        config_id="support-main",
                        did="+15557654321",
                        agent_name="Support Agent",
                        persona_prompt="Help troubleshoot service issues.",
                        kb_collection="support-faq",
                        llm_provider="openai",
                        llm_model="gpt-realtime-mini",
                        tts_provider="deepgram",
                        tts_model="aura-2-thalia-en",
                        tts_voice="thalia",
                        escalation_triggers=["manager"],
                        active=False,
                        updated_at=now - timedelta(minutes=1),
                    ),
                ]
            ),
        )
        monkeypatch.setattr(main_module, "get_settings", lambda: build_settings())
        monkeypatch.setattr(main_module, "MongoResources", build_mongo_factory(fake_resources))

        app = main_module.create_app()

        with TestClient(app) as client:
            list_calls = client.get("/calls")
            active_calls = client.get("/calls", params={"status": "active"})
            get_call = client.get("/calls/call-100")
            transcript = client.get("/calls/call-100/transcript")
            list_agents = client.get("/agents")
            active_agents = client.get("/agents", params={"active_only": "true"})
            get_agent = client.get("/agents/sales-main")

            assert list_calls.status_code == 200
            assert len(list_calls.json()["items"]) == 2
            assert active_calls.json()["items"][0]["room_name"] == "call-100"
            assert get_call.json()["agent_config_id"] == "sales-main"
            assert [item["turn_index"] for item in transcript.json()["items"]] == [0, 1]
            assert len(list_agents.json()["items"]) == 2
            assert len(active_agents.json()["items"]) == 1
            assert get_agent.json()["did"] == "+15551234567"
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
def test_agents_routes_can_create_and_update_agent_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inserted_paths = add_repo_paths()

    try:
        from app import main as main_module

        fake_resources = FakeMongoResources(
            call_sessions=FakeCallSessionRepository([]),
            transcripts=FakeTranscriptRepository([]),
            agent_configs=FakeAgentConfigRepository([]),
        )
        monkeypatch.setattr(main_module, "get_settings", lambda: build_settings())
        monkeypatch.setattr(main_module, "MongoResources", build_mongo_factory(fake_resources))

        app = main_module.create_app()

        create_payload = {
            "config_id": "main-inbound",
            "did": "+16625640501",
            "agent_name": "Main Reception",
            "persona_prompt": "Greet the caller and route them to the right flow.",
            "kb_collection": "main-faq",
            "llm_provider": "openai",
            "llm_model": "gpt-realtime-mini",
            "tts_provider": "deepgram",
            "tts_model": "aura-2-thalia-en",
            "tts_voice": "thalia",
            "escalation_triggers": ["human", "manager"],
            "transfer_target": "sip:frontdesk@example.com",
            "active": True,
        }

        with TestClient(app) as client:
            created = client.post("/agents", json=create_payload)
            updated = client.put(
                "/agents/main-inbound",
                json={
                    **create_payload,
                    "agent_name": "Main Line",
                    "persona_prompt": "Handle inbound calls for the main number.",
                },
            )
            fetched = client.get("/agents/main-inbound")

        assert created.status_code == 201
        assert created.json()["did"] == "+16625640501"
        assert updated.status_code == 200
        assert updated.json()["agent_name"] == "Main Line"
        assert fetched.status_code == 200
        assert fetched.json()["persona_prompt"] == "Handle inbound calls for the main number."
    finally:
        remove_repo_paths(*inserted_paths)
