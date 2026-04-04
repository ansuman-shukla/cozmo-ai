from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


def load_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[2] / relative_path
    spec = spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_backend_settings_defaults() -> None:
    config = load_module("backend_config", "app/config.py")
    settings = config.Settings(_env_file=None)

    assert settings.app_name == "Cozmo Voice Backend"
    assert settings.port == 8000
    assert settings.metrics_enabled is True
    assert settings.stt_provider == "deepgram"
    assert settings.llm_provider == "gemini"
    assert settings.llm_model == "gemini-3-flash-preview"
    assert settings.livekit_sip_dispatch_rule_name == "cozmo-inbound-dispatch"
    assert settings.livekit_dispatch_agent_name == "inbound-agent"
    assert settings.call_room_prefix == "call-"
    assert settings.kb_top_k == 3
    assert settings.timeout_kb_ms == 200


@pytest.mark.unit
def test_backend_settings_accept_generic_mongodb_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_module("backend_config", "app/config.py")
    monkeypatch.setenv(
        "MONGODB_URI",
        "mongodb+srv://user:pass@cluster.example.mongodb.net/cozmo_voice?retryWrites=true&w=majority",
    )

    settings = config.Settings(_env_file=None)

    assert settings.mongo_uri.startswith("mongodb+srv://")
    assert settings.mongo_database == "cozmo_voice"


@pytest.mark.unit
def test_backend_settings_allow_explicit_database_override(monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_module("backend_config", "app/config.py")
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017/admin")
    monkeypatch.setenv("MONGODB_DB", "cozmo_runtime")

    settings = config.Settings(_env_file=None)

    assert settings.mongo_database == "cozmo_runtime"


@pytest.mark.unit
def test_backend_settings_support_generic_runtime_envs(monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_module("backend_config", "app/config.py")
    monkeypatch.setenv("STT_PROVIDER", "deepgram")
    monkeypatch.setenv("STT_MODEL", "nova-3")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("TTS_PROVIDER", "deepgram")
    monkeypatch.setenv("TTS_MODEL", "aura-2-thalia-en")
    monkeypatch.setenv("TTS_VOICE", "thalia")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("KB_TOP_K", "5")
    monkeypatch.setenv("KB_MIN_SCORE", "0.42")
    monkeypatch.setenv("TIMEOUT_STT_MS", "6000")
    monkeypatch.setenv("TIMEOUT_LLM_MS", "9000")
    monkeypatch.setenv("TIMEOUT_TTS_MS", "7000")
    monkeypatch.setenv("TIMEOUT_KB_MS", "300")
    monkeypatch.setenv("LIVEKIT_SIP_DISPATCH_RULE_NAME", "pstn-dispatch")
    monkeypatch.setenv("LIVEKIT_DISPATCH_AGENT_NAME", "sales-agent")
    monkeypatch.setenv("CALL_ROOM_PREFIX", "pstn-")
    monkeypatch.setenv("API_KEY", "internal-secret")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = config.Settings(_env_file=None)

    assert settings.kb_top_k == 5
    assert settings.kb_min_score == 0.42
    assert settings.livekit_sip_dispatch_rule_name == "pstn-dispatch"
    assert settings.livekit_dispatch_agent_name == "sales-agent"
    assert settings.call_room_prefix == "pstn-"
    assert settings.api_key == "internal-secret"
    assert settings.log_level == "DEBUG"
    assert settings.retrieval_settings().top_k == 5
    assert settings.timeout_settings().llm_ms == 9000


@pytest.mark.unit
def test_backend_settings_accept_gemini_api_key_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_module("backend_config", "app/config.py")
    monkeypatch.setenv("COZMO_GEMINI_API_KEY", "gemini-test-key")

    settings = config.Settings(_env_file=None)

    assert settings.gemini_api_key == "gemini-test-key"
