from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any


def add_repo_paths() -> tuple[str, str]:
    repo_root = Path(__file__).resolve().parents[2]
    backend_root = str(repo_root / "backend")
    contracts_root = str(repo_root / "contracts")
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
        "mongo_uri": "mongodb+srv://user:pass@cluster.example.mongodb.net/cozmo_voice",
        "mongo_database": "cozmo_voice",
        "mongo_server_selection_timeout_ms": 2500,
        "auto_create_indexes": True,
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

    def list(self, *, status: str | None = None, did: str | None = None) -> list[Any]:
        results = self.items
        if status is not None:
            results = [item for item in results if item.status == status]
        if did is not None:
            results = [item for item in results if item.did == did]
        return sorted(results, key=lambda item: item.created_at, reverse=True)


class FakeTranscriptRepository:
    def __init__(self, items: list[Any]) -> None:
        self.items = list(items)
        self.ensure_indexes_called = False

    def ensure_indexes(self) -> list[str]:
        self.ensure_indexes_called = True
        return ["uniq_room_turn", "timestamp_lookup"]

    def list_by_room_name(self, room_name: str) -> list[Any]:
        return sorted(
            [item for item in self.items if item.room_name == room_name],
            key=lambda item: item.turn_index,
        )


class FakeAgentConfigRepository:
    def __init__(self, items: list[Any]) -> None:
        self.items = list(items)
        self.ensure_indexes_called = False

    def ensure_indexes(self) -> list[str]:
        self.ensure_indexes_called = True
        return ["uniq_config_id", "did_active_lookup"]

    def get_by_config_id(self, config_id: str) -> Any | None:
        for item in self.items:
            if item.config_id == config_id:
                return item
        return None

    def get_by_did(self, did: str, *, active_only: bool = True) -> Any | None:
        for item in self.items:
            if item.did == did and (not active_only or item.active):
                return item
        return None

    def list(self, *, active_only: bool | None = None) -> list[Any]:
        results = self.items
        if active_only is not None:
            results = [item for item in results if item.active is active_only]
        return sorted(results, key=lambda item: item.updated_at, reverse=True)


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
    def __init__(
        self,
        *,
        call_sessions: Any,
        transcripts: Any,
        agent_configs: Any,
        webhook_events: Any | None = None,
    ) -> None:
        self.call_sessions = call_sessions
        self.transcripts = transcripts
        self.agent_configs = agent_configs
        self.webhook_events = webhook_events or FakeWebhookEventRepository()
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
