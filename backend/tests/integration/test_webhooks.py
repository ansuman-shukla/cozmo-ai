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


class FakeCallSessionRepository:
    def __init__(self, items: list[Any]) -> None:
        self.items = list(items)
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


class FakeTranscriptRepository:
    def __init__(self, items: list[Any]) -> None:
        self.items = list(items)
        self.ensure_indexes_called = False

    def ensure_indexes(self) -> list[str]:
        self.ensure_indexes_called = True
        return ["uniq_room_turn", "timestamp_lookup"]


class FakeAgentConfigRepository:
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

    def upsert(self, record: Any) -> Any:
        for index, existing in enumerate(self.items):
            if existing.config_id == record.config_id:
                self.items[index] = record
                return record
        self.items.append(record)
        return record


class FakeWebhookEventRepository:
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


class FakeMongoResources:
    def __init__(self, *, call_sessions: Any, transcripts: Any, agent_configs: Any) -> None:
        self.call_sessions = call_sessions
        self.transcripts = transcripts
        self.agent_configs = agent_configs
        self.webhook_events = FakeWebhookEventRepository()
        self.ensure_indexes_called = False
        self.closed = False
        self.connection_args: dict[str, Any] | None = None

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


def build_mongo_factory(fake_resources: FakeMongoResources):
    class FakeMongoResourcesFactory:
        @classmethod
        def from_connection_string(
            cls,
            mongo_uri: str,
            database_name: str,
            *,
            server_selection_timeout_ms: int = 5000,
        ) -> FakeMongoResources:
            fake_resources.connection_args = {
                "mongo_uri": mongo_uri,
                "database_name": database_name,
                "server_selection_timeout_ms": server_selection_timeout_ms,
            }
            return fake_resources

    return FakeMongoResourcesFactory


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


def signed_livekit_request(
    payload: dict[str, Any],
    *,
    api_key: str = "testkey",
    api_secret: str = "testsecret",
    now: datetime | None = None,
) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    authorization = build_livekit_authorization(
        body=body,
        api_key=api_key,
        api_secret=api_secret,
        now=now or datetime.now(UTC),
    )
    return body, {
        "Authorization": authorization,
        "Content-Type": "application/json",
    }


@pytest.mark.integration
def test_livekit_room_started_then_participant_joined_creates_and_updates_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inserted_paths = add_repo_paths()

    try:
        from app import main as main_module
        from cozmo_contracts.models import AgentConfigRecord, CallSessionStatus

        now = datetime.now(UTC)
        fake_resources = FakeMongoResources(
            call_sessions=FakeCallSessionRepository([]),
            transcripts=FakeTranscriptRepository([]),
            agent_configs=FakeAgentConfigRepository(
                [
                    AgentConfigRecord(
                        config_id="sales-main",
                        did="+15559876543",
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
                ]
            ),
        )
        monkeypatch.setattr(main_module, "get_settings", lambda: build_settings())
        monkeypatch.setattr(main_module, "MongoResources", build_mongo_factory(fake_resources))

        app = main_module.create_app()
        room_started_payload = {
            "id": "evt-room-1",
            "createdAt": int(now.timestamp()),
            "event": "room_started",
            "room": {"name": "call-+16625640501-a1b2"},
        }
        participant_joined_payload = {
            "id": "evt-participant-1",
            "createdAt": int((now + timedelta(seconds=5)).timestamp()),
            "event": "participant_joined",
            "room": {"name": "call-+16625640501-a1b2"},
            "participant": {
                "identity": "sip-caller-1",
                "kind": "SIP",
                "attributes": {
                    "sip.trunkPhoneNumber": "+15559876543",
                    "sip.phoneNumber": "+15551234567",
                    "sip.twilio.callSid": "CA123",
                    "sip.callStatus": "active",
                },
            },
        }
        room_started_body, room_started_headers = signed_livekit_request(
            room_started_payload,
            now=now,
        )
        participant_joined_body, participant_joined_headers = signed_livekit_request(
            participant_joined_payload,
            now=now,
        )

        with TestClient(app) as client:
            room_started = client.post(
                "/webhooks/livekit",
                content=room_started_body,
                headers=room_started_headers,
            )
            participant_joined = client.post(
                "/webhooks/livekit",
                content=participant_joined_body,
                headers=participant_joined_headers,
            )

            assert room_started.status_code == 202
            assert participant_joined.status_code == 202
            assert room_started.json()["duplicated"] is False
            assert participant_joined.json()["room_name"] == "call-+16625640501-a1b2"

        stored = fake_resources.call_sessions.get_by_room_name("call-+16625640501-a1b2")
        assert stored is not None
        assert stored.provider_call_id == "CA123"
        assert stored.did == "+15559876543"
        assert stored.ani == "+15551234567"
        assert stored.agent_config_id == "sales-main"
        assert stored.status == CallSessionStatus.ACTIVE
        assert stored.created_at == datetime.fromtimestamp(int(now.timestamp()), UTC)
        assert stored.connected_at == datetime.fromtimestamp(int((now + timedelta(seconds=5)).timestamp()), UTC)
        assert stored.metrics_summary.call_setup_ms == 5000.0
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
def test_livekit_webhook_rejects_missing_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
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
            response = client.post(
                "/webhooks/livekit",
                json={
                    "id": "evt-room-unauthorized",
                    "createdAt": int(datetime.now(UTC).timestamp()),
                    "event": "room_started",
                    "room": {"name": "call-+16625640501-a1b2"},
                },
            )

            assert response.status_code == 401
            assert response.json()["detail"] == "Missing Authorization header"
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
def test_duplicate_livekit_event_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    inserted_paths = add_repo_paths()

    try:
        from app import main as main_module
        from cozmo_contracts.models import AgentConfigRecord

        now = datetime.now(UTC)
        fake_resources = FakeMongoResources(
            call_sessions=FakeCallSessionRepository([]),
            transcripts=FakeTranscriptRepository([]),
            agent_configs=FakeAgentConfigRepository(
                [
                    AgentConfigRecord(
                        config_id="sales-main",
                        did="+15559876543",
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
                ]
            ),
        )
        monkeypatch.setattr(main_module, "get_settings", lambda: build_settings())
        monkeypatch.setattr(main_module, "MongoResources", build_mongo_factory(fake_resources))

        app = main_module.create_app()
        payload = {
            "id": "evt-participant-dup",
            "createdAt": int(now.timestamp()),
            "event": "participant_joined",
            "room": {"name": "call-dup"},
            "participant": {
                "identity": "sip-caller-1",
                "kind": "SIP",
                "attributes": {
                    "sip.trunkPhoneNumber": "+15559876543",
                    "sip.phoneNumber": "+15551234567",
                    "sip.twilio.callSid": "CA999",
                    "sip.callStatus": "active",
                },
            },
        }
        body, headers = signed_livekit_request(payload, now=now)

        with TestClient(app) as client:
            first = client.post("/webhooks/livekit", content=body, headers=headers)
            second = client.post("/webhooks/livekit", content=body, headers=headers)

            assert first.status_code == 202
            assert second.status_code == 202
            assert second.json()["duplicated"] is True

        assert len(fake_resources.call_sessions.items) == 1
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
def test_unknown_did_uses_fallback_agent_config(monkeypatch: pytest.MonkeyPatch) -> None:
    inserted_paths = add_repo_paths()

    try:
        from app import main as main_module
        from cozmo_contracts.models import CallDisposition, CallSessionStatus

        now = datetime.now(UTC)
        fake_resources = FakeMongoResources(
            call_sessions=FakeCallSessionRepository([]),
            transcripts=FakeTranscriptRepository([]),
            agent_configs=FakeAgentConfigRepository([]),
        )
        monkeypatch.setattr(main_module, "get_settings", lambda: build_settings())
        monkeypatch.setattr(main_module, "MongoResources", build_mongo_factory(fake_resources))

        app = main_module.create_app()
        payload = {
            "id": "evt-unknown-did",
            "createdAt": int(now.timestamp()),
            "event": "participant_joined",
            "room": {"name": "call-fallback"},
            "participant": {
                "identity": "sip-caller-2",
                "kind": "SIP",
                "attributes": {
                    "sip.trunkPhoneNumber": "+15550001111",
                    "sip.phoneNumber": "+15551234567",
                    "sip.twilio.callSid": "CA404",
                    "sip.callStatus": "active",
                },
            },
        }
        body, headers = signed_livekit_request(payload, now=now)

        with TestClient(app) as client:
            response = client.post(
                "/webhooks/livekit",
                content=body,
                headers=headers,
            )

            assert response.status_code == 202

        stored = fake_resources.call_sessions.get_by_room_name("call-fallback")
        assert stored is not None
        assert stored.agent_config_id == "fallback-unmapped-did"
        assert stored.status == CallSessionStatus.FAILED
        assert stored.disposition == CallDisposition.SETUP_FAILED
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
def test_twilio_status_updates_existing_session_by_call_sid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inserted_paths = add_repo_paths()

    try:
        from app import main as main_module
        from cozmo_contracts.models import CallDisposition, CallSessionRecord, CallSessionStatus

        now = datetime.now(UTC)
        fake_resources = FakeMongoResources(
            call_sessions=FakeCallSessionRepository(
                [
                    CallSessionRecord(
                        provider="twilio",
                        provider_call_id="CA123",
                        room_name="call-123",
                        did="+15559876543",
                        ani="+15551234567",
                        agent_config_id="sales-main",
                        status=CallSessionStatus.ACTIVE,
                        created_at=now,
                        connected_at=now,
                    ),
                ]
            ),
            transcripts=FakeTranscriptRepository([]),
            agent_configs=FakeAgentConfigRepository([]),
        )
        monkeypatch.setattr(main_module, "get_settings", lambda: build_settings())
        monkeypatch.setattr(main_module, "MongoResources", build_mongo_factory(fake_resources))

        app = main_module.create_app()

        with TestClient(app) as client:
            response = client.post(
                "/webhooks/twilio/status",
                data={
                    "CallSid": "CA123",
                    "CallStatus": "completed",
                    "CallDuration": "42",
                    "Timestamp": "Sun, 24 Aug 2025 16:00:00 +0000",
                    "From": "+15551234567",
                    "To": "+15559876543",
                },
            )

            assert response.status_code == 202
            assert response.json()["duplicated"] is False

        stored = fake_resources.call_sessions.get_by_room_name("call-123")
        assert stored is not None
        assert stored.status == CallSessionStatus.COMPLETED
        assert stored.duration_seconds == 42.0
        assert stored.disposition == CallDisposition.COMPLETED
        assert stored.ended_at is not None
    finally:
        remove_repo_paths(*inserted_paths)
