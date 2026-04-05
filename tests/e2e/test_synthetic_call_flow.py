from __future__ import annotations

from base64 import b64encode, urlsafe_b64encode
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient


def clear_app_modules() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            sys.modules.pop(name, None)


def add_backend_paths() -> tuple[str, str]:
    backend_root = str(Path(__file__).resolve().parents[2] / "backend")
    contracts_root = str(Path(__file__).resolve().parents[2] / "contracts")
    sys.path.insert(0, backend_root)
    sys.path.insert(0, contracts_root)
    return backend_root, contracts_root


def add_agent_paths() -> tuple[str, str]:
    agent_root = str(Path(__file__).resolve().parents[2] / "agent")
    contracts_root = str(Path(__file__).resolve().parents[2] / "contracts")
    sys.path.insert(0, agent_root)
    sys.path.insert(0, contracts_root)
    return agent_root, contracts_root


def remove_repo_paths(*paths: str) -> None:
    for path in paths:
        if path in sys.path:
            sys.path.remove(path)
    clear_app_modules()


def build_settings(**overrides: Any) -> SimpleNamespace:
    defaults = {
        "app_name": "Cozmo Voice Backend",
        "environment": "test",
        "log_level": "INFO",
        "mongo_uri": "mongodb+srv://user:pass@cluster.example.mongodb.net/cozmo_voice",
        "mongo_database": "cozmo_voice",
        "mongo_server_selection_timeout_ms": 2500,
        "auto_create_indexes": True,
        "livekit_url": "wss://riverline-rzxihp3i.livekit.cloud",
        "livekit_api_key": "testkey",
        "livekit_api_secret": "testsecret",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def encode_segment(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def build_livekit_authorization(
    *,
    body: bytes,
    api_key: str,
    api_secret: str,
    now: datetime,
    expires_in_seconds: int = 300,
) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {
        "iss": api_key,
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp()),
        "sha256": b64encode(hashlib.sha256(body).digest()).decode("ascii"),
    }
    header_segment = encode_segment(header)
    payload_segment = encode_segment(claims)
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature = hmac.new(api_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_segment = urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"Bearer {header_segment}.{payload_segment}.{signature_segment}"


def signed_livekit_request(payload: dict[str, Any], *, now: datetime) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return body, {
        "Authorization": build_livekit_authorization(
            body=body,
            api_key="testkey",
            api_secret="testsecret",
            now=now,
        ),
        "Content-Type": "application/json",
    }


class SharedCallSessionRepository:
    def __init__(self, items: list[Any] | None = None) -> None:
        self.items = list(items or [])
        self.ensure_indexes_called = False

    def ensure_indexes(self) -> list[str]:
        self.ensure_indexes_called = True
        return ["uniq_provider_call_id", "uniq_room_name"]

    def get_by_room_name(self, room_name: str) -> Any | None:
        for item in self.items:
            if item.room_name == room_name:
                return item
        return None

    def get_by_provider_call_id(self, provider_call_id: str) -> Any | None:
        for item in self.items:
            if item.provider_call_id == provider_call_id:
                return item
        return None

    def upsert(self, record: Any) -> Any:
        for index, existing in enumerate(self.items):
            if existing.room_name == record.room_name:
                self.items[index] = record
                return record
        self.items.append(record)
        return record

    def list(self, *, status: str | None = None, did: str | None = None) -> list[Any]:
        results = self.items
        if status is not None:
            results = [item for item in results if item.status == status]
        if did is not None:
            results = [item for item in results if item.did == did]
        return sorted(results, key=lambda item: item.created_at, reverse=True)


class SharedTranscriptRepository:
    def __init__(self) -> None:
        self.items: list[Any] = []
        self.ensure_indexes_called = False

    def ensure_indexes(self) -> list[str]:
        self.ensure_indexes_called = True
        return ["uniq_room_turn", "timestamp_lookup"]

    def append_transcript_turn(self, turn: Any) -> Any:
        self.items.append(turn)
        return turn

    def next_turn_index(self, room_name: str) -> int:
        room_turns = [item for item in self.items if item.room_name == room_name]
        if not room_turns:
            return 0
        return max(item.turn_index for item in room_turns) + 1

    def mark_transcript_turn_interrupted(self, room_name: str, turn_index: int) -> Any | None:
        for item in self.items:
            if item.room_name == room_name and item.turn_index == turn_index:
                item.interrupted = True
                return item
        return None

    def list_by_room_name(self, room_name: str) -> list[Any]:
        return sorted(
            [item for item in self.items if item.room_name == room_name],
            key=lambda item: item.turn_index,
        )


class SharedAgentConfigRepository:
    def __init__(self, items: list[Any]) -> None:
        self.items = list(items)
        self.ensure_indexes_called = False

    def ensure_indexes(self) -> list[str]:
        self.ensure_indexes_called = True
        return ["uniq_config_id", "did_active_lookup"]

    def get_by_did(self, did: str, *, active_only: bool = True) -> Any | None:
        for item in self.items:
            if item.did == did and (not active_only or item.active):
                return item
        return None

    def get_by_config_id(self, config_id: str) -> Any | None:
        for item in self.items:
            if item.config_id == config_id:
                return item
        return None

    def list(self, *, active_only: bool | None = None) -> list[Any]:
        results = self.items
        if active_only is not None:
            results = [item for item in results if item.active is active_only]
        return list(results)


class SharedWebhookEventRepository:
    def __init__(self) -> None:
        self.claimed: set[tuple[str, str]] = set()
        self.ensure_indexes_called = False

    def ensure_indexes(self) -> list[str]:
        self.ensure_indexes_called = True
        return ["uniq_source_event_id"]

    def claim(self, *, source: str, event_id: str, metadata: dict[str, Any]) -> bool:
        key = (source, event_id)
        if key in self.claimed:
            return False
        self.claimed.add(key)
        return True


class SharedMongoResources:
    def __init__(self, *, call_sessions: Any, transcripts: Any, agent_configs: Any) -> None:
        self.call_sessions = call_sessions
        self.transcripts = transcripts
        self.agent_configs = agent_configs
        self.webhook_events = SharedWebhookEventRepository()
        self.ensure_indexes_called = False
        self.closed = False

    def ensure_indexes(self) -> dict[str, list[str]]:
        self.ensure_indexes_called = True
        return {
            "call_sessions": self.call_sessions.ensure_indexes(),
            "transcripts": self.transcripts.ensure_indexes(),
            "agent_configs": self.agent_configs.ensure_indexes(),
            "webhook_events": self.webhook_events.ensure_indexes(),
        }

    def close(self) -> None:
        self.closed = True


def build_mongo_factory(fake_resources: SharedMongoResources):
    class FakeMongoResourcesFactory:
        @classmethod
        def from_connection_string(
            cls,
            mongo_uri: str,
            database_name: str,
            *,
            server_selection_timeout_ms: int = 5000,
        ) -> SharedMongoResources:
            return fake_resources

    return FakeMongoResourcesFactory


class FakeSttClient:
    async def transcribe(self, audio_input: bytes) -> str:
        assert audio_input == b"synthetic-audio"
        return "I need pricing details"


class FakeLlmClient:
    async def complete(self, chat_ctx):
        from app.pipeline.llm import LlmResponse

        return LlmResponse(
            text="The starter plan begins at 29 dollars per month.",
            provider="gemini",
            model="gemini-3-flash-preview",
        )


class FakeTtsClient:
    async def synthesize(self, chunks):
        return tuple(chunk.text for chunk in chunks)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_local_synthetic_call_flow_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    backend_paths = add_backend_paths()
    room_name = "call-+16625640501-e2e"

    try:
        from app import main as backend_main
        from cozmo_contracts.models import AgentConfigRecord, CallSessionStatus

        now = datetime.now(UTC)
        agent_config = AgentConfigRecord(
            config_id="main-inbound",
            did="+16625640501",
            agent_name="Main Reception",
            persona_prompt="Answer clearly, ground pricing answers, and escalate when needed.",
            kb_collection="main-faq",
            llm_provider="gemini",
            llm_model="gemini-3-flash-preview",
            tts_provider="deepgram",
            tts_model="aura-2-thalia-en",
            tts_voice="thalia",
            escalation_triggers=["human", "agent"],
            active=True,
        )
        shared_resources = SharedMongoResources(
            call_sessions=SharedCallSessionRepository(),
            transcripts=SharedTranscriptRepository(),
            agent_configs=SharedAgentConfigRepository([agent_config]),
        )
        monkeypatch.setattr(backend_main, "get_settings", lambda: build_settings())
        monkeypatch.setattr(backend_main, "MongoResources", build_mongo_factory(shared_resources))

        app = backend_main.create_app()

        room_started_payload = {
            "id": "evt-room-started-e2e",
            "createdAt": int(now.timestamp()),
            "event": "room_started",
            "room": {"name": room_name},
        }
        participant_joined_payload = {
            "id": "evt-participant-joined-e2e",
            "createdAt": int((now + timedelta(seconds=4)).timestamp()),
            "event": "participant_joined",
            "room": {"name": room_name},
            "participant": {
                "identity": "sip-caller-e2e",
                "kind": "SIP",
                "attributes": {
                    "sip.trunkPhoneNumber": "+16625640501",
                    "sip.phoneNumber": "+919262561716",
                    "sip.twilio.callSid": "CA-e2e-001",
                    "sip.callStatus": "active",
                },
            },
        }

        room_started_body, room_started_headers = signed_livekit_request(room_started_payload, now=now)
        participant_joined_body, participant_joined_headers = signed_livekit_request(
            participant_joined_payload,
            now=now,
        )

        with TestClient(app) as client:
            room_started_response = client.post(
                "/webhooks/livekit",
                content=room_started_body,
                headers=room_started_headers,
            )
            participant_joined_response = client.post(
                "/webhooks/livekit",
                content=participant_joined_body,
                headers=participant_joined_headers,
            )

            assert room_started_response.status_code == 202
            assert participant_joined_response.status_code == 202
            call_before_pipeline = client.get(f"/calls/{room_name}")
            assert call_before_pipeline.status_code == 200
            assert call_before_pipeline.json()["status"] == CallSessionStatus.ACTIVE.value
            assert call_before_pipeline.json()["metrics_summary"]["call_setup_ms"] == 4000.0

            remove_repo_paths(*backend_paths)
            agent_paths = add_agent_paths()
            try:
                from app.dialog.conversation import ConversationState
                from app.pipeline.rag import RetrievedChunk
                from app.pipeline.turns import TurnPipeline
                from app.transcripts import TranscriptRecorder
                from cozmo_contracts.runtime import AgentRuntimeConfig

                runtime_config = AgentRuntimeConfig.from_agent_config(agent_config)
                recorder = TranscriptRecorder.from_sink(
                    room_name=room_name,
                    sink=shared_resources.transcripts,
                )
                pipeline = TurnPipeline(
                    runtime_config=runtime_config,
                    conversation=ConversationState(),
                    stt_client=FakeSttClient(),
                    llm_client=FakeLlmClient(),
                    tts_client=FakeTtsClient(),
                    worker_name="cozmo-agent-e2e",
                    transcript_recorder=recorder,
                )

                result = await pipeline.run_audio_turn(
                    b"synthetic-audio",
                    knowledge_chunks=(
                        RetrievedChunk(
                            chunk_id="pricing-1",
                            text="The starter plan begins at 29 dollars per month.",
                            score=0.91,
                        ),
                    ),
                    retrieval_attempted=True,
                )
                assert "29 dollars per month" in result.agent_text
            finally:
                remove_repo_paths(*agent_paths)

            completed_response = client.post(
                "/webhooks/twilio/status",
                data={
                    "CallSid": "CA-e2e-001",
                    "CallStatus": "completed",
                    "CallDuration": "37",
                    "From": "+919262561716",
                    "To": "+16625640501",
                },
            )
            transcript_response = client.get(f"/calls/{room_name}/transcript")
            call_after_pipeline = client.get(f"/calls/{room_name}")

            assert completed_response.status_code == 202
            assert call_after_pipeline.status_code == 200
            assert transcript_response.status_code == 200
            assert [item["speaker"] for item in transcript_response.json()["items"]] == ["user", "agent"]
            assert call_after_pipeline.json()["status"] == CallSessionStatus.COMPLETED.value
            assert call_after_pipeline.json()["duration_seconds"] == 37.0
            assert call_after_pipeline.json()["agent_config_id"] == "main-inbound"
    finally:
        remove_repo_paths(*backend_paths)
