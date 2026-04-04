import os
from datetime import UTC, datetime
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from pymongo import MongoClient


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


@pytest.mark.integration
def test_live_mongo_round_trip_and_index_creation() -> None:
    if os.getenv("RUN_LIVE_MONGO_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_MONGO_TESTS=1 to run live Mongo validation.")

    inserted_paths = add_repo_paths()

    try:
        from app.config import Settings
        from app.services.mongo import AgentConfigRepository, CallSessionRepository, TranscriptRepository
        from cozmo_contracts.models import AgentConfigRecord, CallSessionRecord, CallSessionStatus, TranscriptTurn

        settings = Settings()
        client = MongoClient(
            settings.mongo_uri,
            serverSelectionTimeoutMS=settings.mongo_server_selection_timeout_ms,
        )
        database = client[settings.mongo_database or "cozmo"]

        suffix = uuid4().hex[:8]
        call_collection = database[f"validation_call_sessions_{suffix}"]
        transcript_collection = database[f"validation_transcripts_{suffix}"]
        agent_collection = database[f"validation_agent_configs_{suffix}"]

        try:
            call_repository = CallSessionRepository(call_collection)
            transcript_repository = TranscriptRepository(transcript_collection)
            agent_repository = AgentConfigRepository(agent_collection)

            call_repository.ensure_indexes()
            transcript_repository.ensure_indexes()
            agent_repository.ensure_indexes()

            now = datetime.now(UTC)
            call_record = CallSessionRecord(
                provider="twilio",
                provider_call_id=f"CA{suffix}",
                room_name=f"call-{suffix}",
                did="+15551234567",
                ani="+15557654321",
                agent_config_id=f"sales-{suffix}",
                status=CallSessionStatus.ACTIVE,
                created_at=now,
                connected_at=now,
            )
            transcript_turn = TranscriptTurn(
                room_name=f"call-{suffix}",
                turn_index=0,
                speaker="user",
                text="Need pricing details.",
                timestamp=now,
            )
            agent_config = AgentConfigRecord(
                config_id=f"sales-{suffix}",
                did="+15551234567",
                agent_name="Sales Agent",
                persona_prompt="Help with pricing and plan selection.",
                kb_collection="sales-faq",
                llm_provider=settings.llm_provider,
                llm_model=settings.llm_model,
                tts_provider=settings.tts_provider,
                tts_model=settings.tts_model,
                tts_voice=settings.tts_voice,
                escalation_triggers=["human"],
                transfer_target="sip:sales@example.com",
            )

            stored_call = call_repository.upsert(call_record)
            stored_turn = transcript_repository.insert(transcript_turn)
            stored_agent = agent_repository.upsert(agent_config)

            fetched_call = call_repository.get_by_room_name(call_record.room_name)
            fetched_transcript = transcript_repository.list_by_room_name(call_record.room_name)
            fetched_agent = agent_repository.get_by_config_id(agent_config.config_id)

            call_index_names = set(call_collection.index_information())
            transcript_index_names = set(transcript_collection.index_information())
            agent_index_names = set(agent_collection.index_information())

            assert stored_call.room_name == call_record.room_name
            assert stored_turn.turn_index == 0
            assert stored_agent.config_id == agent_config.config_id
            assert fetched_call is not None
            assert fetched_call.provider_call_id == call_record.provider_call_id
            assert len(fetched_transcript) == 1
            assert fetched_transcript[0].text == "Need pricing details."
            assert fetched_agent is not None
            assert fetched_agent.did == "+15551234567"
            assert "uniq_provider_call_id" in call_index_names
            assert "uniq_room_name" in call_index_names
            assert "uniq_room_turn" in transcript_index_names
            assert "uniq_config_id" in agent_index_names
            assert "did_active_lookup" in agent_index_names
        finally:
            call_collection.drop()
            transcript_collection.drop()
            agent_collection.drop()
            client.close()
    finally:
        remove_repo_paths(*inserted_paths)
