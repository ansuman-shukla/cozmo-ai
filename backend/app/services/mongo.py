"""MongoDB client and repository helpers."""

from dataclasses import dataclass
import logging
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.operations import IndexModel

from cozmo_contracts.models import AgentConfigRecord, CallSessionRecord, TranscriptTurn

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MongoIndexSpec:
    """A declarative MongoDB index definition."""

    name: str
    keys: tuple[tuple[str, int], ...]
    unique: bool = False
    sparse: bool = False
    partial_filter_expression: dict[str, Any] | None = None

    def to_index_model(self) -> IndexModel:
        """Convert the declarative spec into a PyMongo IndexModel."""

        kwargs: dict[str, Any] = {"name": self.name, "unique": self.unique}
        if self.sparse:
            kwargs["sparse"] = True
        if self.partial_filter_expression is not None:
            kwargs["partialFilterExpression"] = self.partial_filter_expression
        return IndexModel(list(self.keys), **kwargs)


def dump_model(document: Any) -> dict[str, Any]:
    """Serialize a Pydantic model into a Mongo-friendly Python dict."""

    return document.model_dump(by_alias=True, mode="python", exclude_none=True)


def dump_model_for_write(document: Any) -> dict[str, Any]:
    """Serialize a model for Mongo writes, excluding immutable `_id`."""

    payload = dump_model(document)
    payload.pop("_id", None)
    return payload


def create_indexes(collection: Any, specs: tuple[MongoIndexSpec, ...]) -> list[str]:
    """Create a batch of indexes from declarative specs."""

    return collection.create_indexes([spec.to_index_model() for spec in specs])


@dataclass(slots=True)
class CallSessionRepository:
    """Persistence helpers for `call_sessions` documents."""

    collection: Any

    @staticmethod
    def index_specs() -> tuple[MongoIndexSpec, ...]:
        return (
            MongoIndexSpec(
                name="uniq_provider_call_id",
                keys=(("provider_call_id", ASCENDING),),
                unique=True,
                partial_filter_expression={"provider_call_id": {"$exists": True, "$type": "string"}},
            ),
            MongoIndexSpec(name="uniq_room_name", keys=(("room_name", ASCENDING),), unique=True),
            MongoIndexSpec(name="did_lookup", keys=(("did", ASCENDING),)),
            MongoIndexSpec(name="status_lookup", keys=(("status", ASCENDING),)),
            MongoIndexSpec(name="created_at_lookup", keys=(("created_at", ASCENDING),)),
        )

    def ensure_indexes(self) -> list[str]:
        return create_indexes(self.collection, self.index_specs())

    def upsert(self, record: CallSessionRecord) -> CallSessionRecord:
        payload = dump_model_for_write(record)
        self.collection.replace_one({"room_name": record.room_name}, payload, upsert=True)
        stored = self.collection.find_one({"room_name": record.room_name})
        return CallSessionRecord.model_validate(stored or payload)

    def get_by_room_name(self, room_name: str) -> CallSessionRecord | None:
        document = self.collection.find_one({"room_name": room_name})
        if document is None:
            return None
        return CallSessionRecord.model_validate(document)

    def get_by_provider_call_id(self, provider_call_id: str) -> CallSessionRecord | None:
        document = self.collection.find_one({"provider_call_id": provider_call_id})
        if document is None:
            return None
        return CallSessionRecord.model_validate(document)

    def list(
        self,
        *,
        status: str | None = None,
        did: str | None = None,
    ) -> list[CallSessionRecord]:
        """Return call-session records filtered by supported query fields."""

        criteria: dict[str, Any] = {}
        if status is not None:
            criteria["status"] = status
        if did is not None:
            criteria["did"] = did

        documents = self.collection.find(criteria)
        if hasattr(documents, "sort"):
            documents = documents.sort("created_at", DESCENDING)
        else:
            documents = sorted(
                documents,
                key=lambda item: item.get("created_at"),
                reverse=True,
            )
        return [CallSessionRecord.model_validate(document) for document in documents]


@dataclass(slots=True)
class TranscriptRepository:
    """Persistence helpers for `transcripts` documents."""

    collection: Any

    @staticmethod
    def index_specs() -> tuple[MongoIndexSpec, ...]:
        return (
            MongoIndexSpec(
                name="uniq_room_turn",
                keys=(("room_name", ASCENDING), ("turn_index", ASCENDING)),
                unique=True,
            ),
            MongoIndexSpec(name="timestamp_lookup", keys=(("timestamp", ASCENDING),)),
        )

    def ensure_indexes(self) -> list[str]:
        return create_indexes(self.collection, self.index_specs())

    def insert(self, turn: TranscriptTurn) -> TranscriptTurn:
        payload = dump_model_for_write(turn)
        self.collection.insert_one(payload)
        return TranscriptTurn.model_validate(payload)

    def list_by_room_name(self, room_name: str) -> list[TranscriptTurn]:
        documents = self.collection.find({"room_name": room_name})
        if isinstance(documents, list):
            documents = sorted(documents, key=lambda item: item["turn_index"])
        elif hasattr(documents, "sort"):
            documents = documents.sort("turn_index", ASCENDING)
        else:
            documents = sorted(list(documents), key=lambda item: item["turn_index"])
        return [TranscriptTurn.model_validate(document) for document in documents]


@dataclass(slots=True)
class AgentConfigRepository:
    """Persistence helpers for `agent_configs` documents."""

    collection: Any

    @staticmethod
    def index_specs() -> tuple[MongoIndexSpec, ...]:
        return (
            MongoIndexSpec(name="uniq_config_id", keys=(("config_id", ASCENDING),), unique=True),
            MongoIndexSpec(name="did_active_lookup", keys=(("did", ASCENDING), ("active", ASCENDING))),
        )

    def ensure_indexes(self) -> list[str]:
        return create_indexes(self.collection, self.index_specs())

    def upsert(self, record: AgentConfigRecord) -> AgentConfigRecord:
        payload = dump_model_for_write(record)
        self.collection.replace_one({"config_id": record.config_id}, payload, upsert=True)
        stored = self.collection.find_one({"config_id": record.config_id})
        return AgentConfigRecord.model_validate(stored or payload)

    def get_by_config_id(self, config_id: str) -> AgentConfigRecord | None:
        document = self.collection.find_one({"config_id": config_id})
        if document is None:
            return None
        return AgentConfigRecord.model_validate(document)

    def get_by_did(self, did: str, *, active_only: bool = True) -> AgentConfigRecord | None:
        criteria: dict[str, Any] = {"did": did}
        if active_only:
            criteria["active"] = True
        document = self.collection.find_one(criteria)
        if document is None:
            return None
        return AgentConfigRecord.model_validate(document)

    def list(self, *, active_only: bool | None = None) -> list[AgentConfigRecord]:
        """Return agent configs, optionally filtered by active state."""

        criteria: dict[str, Any] = {}
        if active_only is not None:
            criteria["active"] = active_only

        documents = self.collection.find(criteria)
        if hasattr(documents, "sort"):
            documents = documents.sort("updated_at", DESCENDING)
        else:
            documents = sorted(
                documents,
                key=lambda item: (item.get("updated_at"), item.get("config_id")),
                reverse=True,
            )
        return [AgentConfigRecord.model_validate(document) for document in documents]


@dataclass(slots=True)
class WebhookEventRepository:
    """Persistence helpers for webhook event idempotency records."""

    collection: Any

    @staticmethod
    def index_specs() -> tuple[MongoIndexSpec, ...]:
        return (
            MongoIndexSpec(
                name="uniq_source_event_id",
                keys=(("source", ASCENDING), ("event_id", ASCENDING)),
                unique=True,
            ),
        )

    def ensure_indexes(self) -> list[str]:
        return create_indexes(self.collection, self.index_specs())

    def claim(self, *, source: str, event_id: str, metadata: dict[str, Any]) -> bool:
        document = {
            "source": source,
            "event_id": event_id,
            "metadata": metadata,
        }
        try:
            self.collection.insert_one(document)
        except DuplicateKeyError:
            return False
        return True


@dataclass(slots=True)
class MongoResources:
    """Live MongoDB resources bound to the backend service."""

    client: MongoClient
    database: Any
    call_sessions: CallSessionRepository
    transcripts: TranscriptRepository
    agent_configs: AgentConfigRepository
    webhook_events: WebhookEventRepository

    @classmethod
    def from_connection_string(
        cls,
        mongo_uri: str,
        database_name: str,
        *,
        server_selection_timeout_ms: int = 5000,
    ) -> "MongoResources":
        """Create repositories backed by a shared MongoClient."""

        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=server_selection_timeout_ms)
        database = client[database_name]
        return cls(
            client=client,
            database=database,
            call_sessions=CallSessionRepository(database["call_sessions"]),
            transcripts=TranscriptRepository(database["transcripts"]),
            agent_configs=AgentConfigRepository(database["agent_configs"]),
            webhook_events=WebhookEventRepository(database["webhook_events"]),
        )

    def ensure_indexes(self) -> dict[str, list[str]]:
        """Create the documented collection indexes for the backend."""

        return {
            "call_sessions": self.call_sessions.ensure_indexes(),
            "transcripts": self.transcripts.ensure_indexes(),
            "agent_configs": self.agent_configs.ensure_indexes(),
            "webhook_events": self.webhook_events.ensure_indexes(),
        }

    def ping(self) -> bool:
        """Check whether the configured MongoDB deployment is reachable."""

        try:
            self.database.command("ping")
        except PyMongoError:
            LOGGER.exception("MongoDB ping failed")
            return False
        return True

    def close(self) -> None:
        """Close the underlying MongoClient."""

        self.client.close()
