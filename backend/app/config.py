"""Runtime settings for the backend service."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from cozmo_contracts.runtime import RetrievalSettings, TimeoutSettings

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_ENV_FILE = REPO_ROOT / ".env"


def resolve_mongo_database_name(mongo_uri: str, explicit_database: str | None = None) -> str:
    """Resolve the Mongo database name from an explicit setting or the URI path."""

    if explicit_database:
        return explicit_database

    uri_path = urlsplit(mongo_uri).path.lstrip("/")
    if not uri_path:
        return "cozmo"

    database_segment = uri_path.split("/", maxsplit=1)[0]
    if not database_segment:
        return "cozmo"

    return database_segment.split(".", maxsplit=1)[0] or "cozmo"


class Settings(BaseSettings):
    """Centralized environment-backed settings for the FastAPI service."""

    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="COZMO_BACKEND_",
        extra="ignore",
    )

    app_name: str = "Cozmo Voice Backend"
    environment: str = Field(default="development")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)
    mongo_uri: str = Field(
        default="mongodb://localhost:27017/cozmo",
        validation_alias=AliasChoices("COZMO_BACKEND_MONGO_URI", "MONGODB_URI"),
    )
    mongo_database: str | None = Field(
        default=None,
        validation_alias=AliasChoices("COZMO_BACKEND_MONGO_DATABASE", "MONGODB_DB"),
    )
    chroma_uri: str = Field(default="http://localhost:8000")
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("COZMO_BACKEND_REDIS_URL", "REDIS_URL"),
    )
    livekit_url: str = Field(default="ws://localhost:7880")
    livekit_api_key: str = Field(default="devkey")
    livekit_api_secret: str = Field(default="secret")
    livekit_sip_trunk_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("COZMO_BACKEND_LIVEKIT_SIP_TRUNK_ID", "LIVEKIT_SIP_TRUNK_ID"),
    )
    livekit_sip_dispatch_rule_name: str = Field(
        default="cozmo-inbound-dispatch",
        validation_alias=AliasChoices(
            "COZMO_BACKEND_LIVEKIT_SIP_DISPATCH_RULE_NAME",
            "LIVEKIT_SIP_DISPATCH_RULE_NAME",
        ),
        min_length=1,
    )
    livekit_dispatch_agent_name: str = Field(
        default="inbound-agent",
        validation_alias=AliasChoices(
            "COZMO_BACKEND_LIVEKIT_DISPATCH_AGENT_NAME",
            "LIVEKIT_DISPATCH_AGENT_NAME",
        ),
        min_length=1,
    )
    call_room_prefix: str = Field(
        default="call-",
        validation_alias=AliasChoices("COZMO_BACKEND_CALL_ROOM_PREFIX", "CALL_ROOM_PREFIX"),
        min_length=1,
    )
    twilio_account_sid: str | None = Field(
        default=None,
        validation_alias=AliasChoices("COZMO_TWILIO_ACCOUNT_SID", "TWILIO_ACCOUNT_SID"),
    )
    twilio_auth_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("COZMO_TWILIO_AUTH_TOKEN", "TWILIO_AUTH_TOKEN"),
    )
    twilio_trunk_name: str = Field(
        default="cozmo-inbound",
        validation_alias=AliasChoices("COZMO_TWILIO_TRUNK_NAME", "TWILIO_TRUNK_NAME"),
    )
    twilio_sip_domain: str | None = Field(
        default=None,
        validation_alias=AliasChoices("COZMO_TWILIO_SIP_DOMAIN", "TWILIO_SIP_DOMAIN"),
    )
    deepgram_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("COZMO_DEEPGRAM_API_KEY", "DEEPGRAM_API_KEY"),
    )
    gemini_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "COZMO_GEMINI_API_KEY",
            "COZMO_BACKEND_GEMINI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
        ),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("COZMO_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    stt_provider: str = Field(
        default="deepgram",
        validation_alias=AliasChoices("COZMO_BACKEND_STT_PROVIDER", "STT_PROVIDER"),
        min_length=1,
    )
    stt_model: str = Field(
        default="nova-3",
        validation_alias=AliasChoices("COZMO_BACKEND_STT_MODEL", "STT_MODEL"),
        min_length=1,
    )
    tts_provider: str = Field(
        default="deepgram",
        validation_alias=AliasChoices("COZMO_BACKEND_TTS_PROVIDER", "TTS_PROVIDER"),
        min_length=1,
    )
    tts_model: str = Field(
        default="aura-2-thalia-en",
        validation_alias=AliasChoices("COZMO_BACKEND_TTS_MODEL", "TTS_MODEL"),
        min_length=1,
    )
    tts_voice: str = Field(
        default="thalia",
        validation_alias=AliasChoices("COZMO_BACKEND_TTS_VOICE", "TTS_VOICE"),
        min_length=1,
    )
    llm_provider: str = Field(
        default="gemini",
        validation_alias=AliasChoices("COZMO_BACKEND_LLM_PROVIDER", "LLM_PROVIDER"),
        min_length=1,
    )
    llm_model: str = Field(
        default="gemini-3-flash-preview",
        validation_alias=AliasChoices("COZMO_BACKEND_LLM_MODEL", "LLM_MODEL"),
        min_length=1,
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias=AliasChoices("COZMO_BACKEND_EMBEDDING_MODEL", "EMBEDDING_MODEL"),
        min_length=1,
    )
    kb_top_k: int = Field(
        default=3,
        ge=1,
        le=10,
        validation_alias=AliasChoices("COZMO_BACKEND_KB_TOP_K", "KB_TOP_K"),
    )
    kb_min_score: float = Field(
        default=0.35,
        ge=0,
        le=1,
        validation_alias=AliasChoices("COZMO_BACKEND_KB_MIN_SCORE", "KB_MIN_SCORE"),
    )
    max_history_turns: int = Field(
        default=10,
        ge=1,
        le=100,
        validation_alias=AliasChoices("COZMO_BACKEND_MAX_HISTORY_TURNS", "MAX_HISTORY_TURNS"),
    )
    timeout_stt_ms: int = Field(
        default=5000,
        ge=1,
        validation_alias=AliasChoices("COZMO_BACKEND_TIMEOUT_STT_MS", "TIMEOUT_STT_MS"),
    )
    timeout_llm_ms: int = Field(
        default=8000,
        ge=1,
        validation_alias=AliasChoices("COZMO_BACKEND_TIMEOUT_LLM_MS", "TIMEOUT_LLM_MS"),
    )
    timeout_tts_ms: int = Field(
        default=5000,
        ge=1,
        validation_alias=AliasChoices("COZMO_BACKEND_TIMEOUT_TTS_MS", "TIMEOUT_TTS_MS"),
    )
    timeout_kb_ms: int = Field(
        default=200,
        ge=1,
        validation_alias=AliasChoices("COZMO_BACKEND_TIMEOUT_KB_MS", "TIMEOUT_KB_MS"),
    )
    api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("COZMO_BACKEND_API_KEY", "API_KEY"),
    )
    log_level: str = Field(
        default="INFO",
        validation_alias=AliasChoices("COZMO_BACKEND_LOG_LEVEL", "LOG_LEVEL"),
        min_length=1,
    )
    metrics_enabled: bool = Field(default=True)
    auto_create_indexes: bool = True
    mongo_server_selection_timeout_ms: int = Field(default=5000, ge=1)

    @model_validator(mode="after")
    def populate_database_name(self) -> "Settings":
        """Fill the effective Mongo database name from the URI when needed."""

        self.mongo_database = resolve_mongo_database_name(self.mongo_uri, self.mongo_database)
        return self

    def retrieval_settings(self) -> RetrievalSettings:
        """Project settings into the shared retrieval configuration shape."""

        return RetrievalSettings(
            embedding_model=self.embedding_model,
            top_k=self.kb_top_k,
            min_score=self.kb_min_score,
        )

    def timeout_settings(self) -> TimeoutSettings:
        """Project settings into the shared timeout configuration shape."""

        return TimeoutSettings(
            stt_ms=self.timeout_stt_ms,
            llm_ms=self.timeout_llm_ms,
            tts_ms=self.timeout_tts_ms,
            kb_ms=self.timeout_kb_ms,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build and cache the application settings once per process."""

    return Settings()
