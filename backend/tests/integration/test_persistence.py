from datetime import UTC, datetime
from pathlib import Path
import sys

import pytest


class FakeCollection:
    def __init__(self) -> None:
        self.documents: list[dict] = []
        self.created_indexes: list[object] = []
        self.synthetic_id_counter = 0

    def replace_one(self, criteria: dict, document: dict, upsert: bool = False) -> None:
        for index, existing in enumerate(self.documents):
            if all(existing.get(key) == value for key, value in criteria.items()):
                replaced = document.copy()
                replaced["_id"] = existing.get("_id")
                self.documents[index] = replaced
                return
        if upsert:
            inserted = document.copy()
            self.synthetic_id_counter += 1
            inserted["_id"] = f"fake-{self.synthetic_id_counter}"
            self.documents.append(inserted)

    def insert_one(self, document: dict) -> None:
        inserted = document.copy()
        self.synthetic_id_counter += 1
        inserted["_id"] = f"fake-{self.synthetic_id_counter}"
        self.documents.append(inserted)

    def find_one(self, criteria: dict) -> dict | None:
        for document in self.documents:
            if all(document.get(key) == value for key, value in criteria.items()):
                return document.copy()
        return None

    def find(self, criteria: dict) -> list[dict]:
        matches = []
        for document in self.documents:
            if all(document.get(key) == value for key, value in criteria.items()):
                matches.append(document.copy())
        return matches

    def create_indexes(self, indexes: list[object]) -> list[str]:
        self.created_indexes.extend(indexes)
        return [getattr(index, "document", {}).get("name", "") for index in indexes]


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
        if name == "app" or name.startswith("app.") or name == "cozmo_contracts" or name.startswith("cozmo_contracts."):
            sys.modules.pop(name, None)


@pytest.mark.integration
def test_call_session_repository_round_trip() -> None:
    inserted_paths = add_repo_paths()

    try:
        from app.services.mongo import CallSessionRepository
        from cozmo_contracts.models import CallSessionRecord, CallSessionStatus

        repository = CallSessionRepository(FakeCollection())
        record = CallSessionRecord(
            provider="twilio",
            provider_call_id="CA123",
            room_name="call-123",
            did="+15551234567",
            ani="+15557654321",
            agent_config_id="sales-main",
            status=CallSessionStatus.ACTIVE,
            created_at=datetime.now(UTC),
            connected_at=datetime.now(UTC),
        )

        stored = repository.upsert(record)
        fetched = repository.get_by_room_name("call-123")

        assert stored.room_name == "call-123"
        assert fetched is not None
        assert fetched.provider_call_id == "CA123"
        assert fetched.agent_config_id == "sales-main"
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
def test_call_session_repository_second_upsert_preserves_mongo_id() -> None:
    inserted_paths = add_repo_paths()

    try:
        from app.services.mongo import CallSessionRepository
        from cozmo_contracts.models import CallSessionRecord, CallSessionStatus

        repository = CallSessionRepository(FakeCollection())
        created_at = datetime.now(UTC)
        initial = CallSessionRecord(
            provider="twilio",
            provider_call_id="CA123",
            room_name="call-123",
            did="+15551234567",
            ani="+15557654321",
            agent_config_id="sales-main",
            status=CallSessionStatus.CREATED,
            created_at=created_at,
        )

        repository.upsert(initial)
        fetched = repository.get_by_room_name("call-123")

        assert fetched is not None
        original_id = fetched.id
        updated = fetched.model_copy(update={"status": CallSessionStatus.ACTIVE, "connected_at": datetime.now(UTC)})

        stored = repository.upsert(updated)

        assert stored.id == original_id
        assert stored.status == CallSessionStatus.ACTIVE
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
def test_transcript_repository_round_trip() -> None:
    inserted_paths = add_repo_paths()

    try:
        from app.services.mongo import TranscriptRepository
        from cozmo_contracts.models import TranscriptTurn

        repository = TranscriptRepository(FakeCollection())
        turn = TranscriptTurn(
            room_name="call-123",
            turn_index=0,
            speaker="user",
            text="hello there",
            timestamp=datetime.now(UTC),
        )

        repository.insert(turn)
        transcript = repository.list_by_room_name("call-123")

        assert len(transcript) == 1
        assert transcript[0].text == "hello there"
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
def test_agent_config_repository_round_trip() -> None:
    inserted_paths = add_repo_paths()

    try:
        from app.services.mongo import AgentConfigRepository
        from cozmo_contracts.models import AgentConfigRecord

        repository = AgentConfigRepository(FakeCollection())
        config = AgentConfigRecord(
            config_id="sales-main",
            did="+15551234567",
            agent_name="Sales Agent",
            persona_prompt="Help the caller with plan selection.",
            kb_collection="sales-faq",
            llm_provider="openai",
            llm_model="gpt-realtime-mini",
            tts_provider="deepgram",
            tts_model="aura-2-thalia-en",
            tts_voice="thalia",
            escalation_triggers=["human"],
            transfer_target="sip:desk@example.com",
        )

        repository.upsert(config)
        fetched = repository.get_by_did("+15551234567")

        assert fetched is not None
        assert fetched.config_id == "sales-main"
        assert fetched.transfer_target == "sip:desk@example.com"
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
def test_repositories_declare_expected_indexes() -> None:
    inserted_paths = add_repo_paths()

    try:
        from app.services.mongo import AgentConfigRepository, CallSessionRepository, TranscriptRepository

        call_indexes = CallSessionRepository.index_specs()
        transcript_indexes = TranscriptRepository.index_specs()
        agent_indexes = AgentConfigRepository.index_specs()

        assert any(spec.name == "uniq_provider_call_id" and spec.unique for spec in call_indexes)
        assert any(spec.name == "uniq_room_name" and spec.unique for spec in call_indexes)
        assert any(spec.name == "uniq_room_turn" and spec.unique for spec in transcript_indexes)
        assert any(spec.name == "uniq_config_id" and spec.unique for spec in agent_indexes)
        assert any(spec.name == "did_active_lookup" for spec in agent_indexes)
    finally:
        remove_repo_paths(*inserted_paths)
