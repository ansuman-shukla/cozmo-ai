from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import os

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
def test_agent_settings_defaults() -> None:
    config = load_module("agent_config", "app/config.py")
    settings = config.Settings(_env_file=None)

    assert settings.worker_name == "cozmo-agent-1"
    assert settings.llm_provider == "gemini"
    assert settings.llm_model == "gemini-3-flash-preview"
    assert settings.livekit_dispatch_agent_name == "inbound-agent"
    assert settings.call_room_prefix == "call-"
    assert settings.backend_base_url == "http://localhost:8000"
    assert settings.max_history_turns == 10
    assert settings.max_jobs_per_worker_server == 8


@pytest.mark.unit
def test_agent_settings_accept_generic_mongodb_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_module("agent_config", "app/config.py")
    monkeypatch.setenv(
        "MONGODB_URI",
        "mongodb+srv://user:pass@cluster.example.mongodb.net/cozmo_voice?retryWrites=true&w=majority",
    )

    settings = config.Settings(_env_file=None)

    assert settings.mongo_uri.startswith("mongodb+srv://")
    assert settings.mongo_database == "cozmo_voice"


@pytest.mark.unit
def test_agent_settings_support_generic_runtime_envs(monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_module("agent_config", "app/config.py")
    monkeypatch.setenv("STT_PROVIDER", "deepgram")
    monkeypatch.setenv("STT_MODEL", "nova-3")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("TTS_PROVIDER", "deepgram")
    monkeypatch.setenv("TTS_MODEL", "aura-2-thalia-en")
    monkeypatch.setenv("TTS_VOICE", "thalia")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("KB_TOP_K", "4")
    monkeypatch.setenv("KB_MIN_SCORE", "0.5")
    monkeypatch.setenv("MAX_HISTORY_TURNS", "12")
    monkeypatch.setenv("MAX_JOBS_PER_WORKER_SERVER", "16")
    monkeypatch.setenv("LIVEKIT_DISPATCH_AGENT_NAME", "voice-agent")
    monkeypatch.setenv("CALL_ROOM_PREFIX", "support-")
    monkeypatch.setenv("TIMEOUT_STT_MS", "6100")
    monkeypatch.setenv("TIMEOUT_LLM_MS", "9100")
    monkeypatch.setenv("TIMEOUT_TTS_MS", "7100")
    monkeypatch.setenv("TIMEOUT_KB_MS", "310")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = config.Settings(_env_file=None)

    assert settings.max_history_turns == 12
    assert settings.max_jobs_per_worker_server == 16
    assert settings.livekit_dispatch_agent_name == "voice-agent"
    assert settings.call_room_prefix == "support-"
    assert settings.log_level == "DEBUG"
    assert settings.retrieval_settings().min_score == 0.5
    assert settings.timeout_settings().tts_ms == 7100


@pytest.mark.unit
def test_agent_settings_accept_gemini_api_key_and_export_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_module("agent_config", "app/config.py")
    monkeypatch.setenv("COZMO_GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.setenv("COZMO_DEEPGRAM_API_KEY", "deepgram-test-key")

    settings = config.Settings(_env_file=None)
    config.export_provider_environment(settings)

    assert settings.gemini_api_key == "gemini-test-key"
    assert os.environ["GOOGLE_API_KEY"] == "gemini-test-key"
    assert os.environ["DEEPGRAM_API_KEY"] == "deepgram-test-key"
