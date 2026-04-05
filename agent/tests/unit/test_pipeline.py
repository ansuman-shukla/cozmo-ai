from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


def load_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[2] / relative_path
    spec = spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def add_repo_paths() -> tuple[str, str]:
    agent_root = str(Path(__file__).resolve().parents[2])
    contracts_root = str(Path(__file__).resolve().parents[3] / "contracts")
    sys.path.insert(0, agent_root)
    sys.path.insert(0, contracts_root)
    return agent_root, contracts_root


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
            or name
            in {
                "agent_llm_pipeline",
                "agent_rag_pipeline",
                "agent_stt_pipeline",
                "agent_tts_pipeline",
                "agent_turns_pipeline_unit",
            }
        ):
            sys.modules.pop(name, None)


@pytest.mark.unit
def test_prompt_builder_includes_persona_history_and_kb_chunks() -> None:
    inserted_paths = add_repo_paths()

    try:
        llm_module = load_module("agent_llm_pipeline", "app/pipeline/llm.py")
        rag_module = load_module("agent_rag_pipeline", "app/pipeline/rag.py")
        from app.dialog.conversation import ConversationState
        from cozmo_contracts.runtime import AgentRuntimeConfig

        runtime_config = AgentRuntimeConfig(
            config_id="main-inbound",
            did="+16625640501",
            agent_name="Main Reception",
            persona_prompt="Greet callers warmly and answer with grounded facts.",
            kb_collection="main-faq",
            llm_provider="gemini",
            llm_model="gemini-3-flash-preview",
            tts_provider="deepgram",
            tts_model="aura-2-thalia-en",
            tts_voice="thalia",
            escalation_triggers=["human", "manager"],
            max_history_turns=4,
        )
        conversation = ConversationState()
        conversation.append("user", "I need pricing details.")
        conversation.append("agent", "I can help with that.")
        chunks = [
            rag_module.RetrievedChunk(
                chunk_id="pricing-1",
                text="The starter plan begins at 29 dollars per month.",
                score=0.91,
            )
        ]

        prompt_builder = llm_module.PromptBuilder()
        chat_ctx = prompt_builder.build_chat_context(
            runtime_config=runtime_config,
            conversation=conversation,
            pending_user_text="Can you explain the annual discount?",
            knowledge_chunks=chunks,
        )
        messages = chat_ctx.messages()
        system_text = " ".join(messages[0].content)

        assert messages[0].role == "system"
        assert "Greet callers warmly" in system_text
        assert "starter plan begins at 29 dollars per month" in system_text
        assert "human, manager" in system_text
        assert [message.role for message in messages[1:]] == ["user", "assistant", "user"]
        assert "annual discount" in " ".join(messages[-1].content)
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
def test_rag_adapter_filters_and_sorts_hits() -> None:
    rag_module = load_module("agent_rag_pipeline", "app/pipeline/rag.py")
    adapter = rag_module.RagAdapter(top_k=2, min_score=0.5)

    chunks = adapter.normalize_hits(
        [
            {"chunk_id": "low", "text": "skip", "score": 0.2},
            {"chunk_id": "mid", "text": "keep second", "score": 0.7},
            {"chunk_id": "high", "text": "keep first", "score": 0.9},
            {"chunk_id": "empty", "text": "", "score": 0.8},
        ]
    )

    assert [chunk.chunk_id for chunk in chunks] == ["high", "mid"]


@pytest.mark.unit
def test_llm_adapter_builds_google_provider_with_gemini_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    inserted_paths = add_repo_paths()

    try:
        llm_module = load_module("agent_llm_pipeline", "app/pipeline/llm.py")
        calls: list[dict[str, object]] = []

        class FakeGoogleModule:
            class LLM:
                def __init__(self, **kwargs):
                    calls.append(kwargs)

        monkeypatch.setattr(llm_module.importlib, "import_module", lambda name: FakeGoogleModule())

        adapter = llm_module.LlmAdapter(
            provider="gemini",
            model="gemini-3-flash-preview",
            api_key="gemini-test-key",
            temperature=0.3,
            max_output_tokens=128,
        )
        adapter.create_provider()

        assert calls == [
            {
                "model": "gemini-3-flash-preview",
                "api_key": "gemini-test-key",
                "temperature": 0.3,
                "max_output_tokens": 128,
            }
        ]
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
def test_stt_and_tts_adapters_create_deepgram_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    stt_module = load_module("agent_stt_pipeline", "app/pipeline/stt.py")
    tts_module = load_module("agent_tts_pipeline", "app/pipeline/tts.py")
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeDeepgramModule:
        class STT:
            def __init__(self, **kwargs):
                calls.append(("stt", kwargs))

        class TTS:
            def __init__(self, **kwargs):
                calls.append(("tts", kwargs))

    monkeypatch.setattr(stt_module.importlib, "import_module", lambda name: FakeDeepgramModule())
    monkeypatch.setattr(tts_module.importlib, "import_module", lambda name: FakeDeepgramModule())

    stt_adapter = stt_module.SttAdapter(provider="deepgram", model="nova-3", api_key="dg-key")
    tts_adapter = tts_module.TtsAdapter(
        provider="deepgram",
        model="aura-2-thalia-en",
        voice="thalia",
        api_key="dg-key",
    )

    stt_adapter.create_provider()
    tts_adapter.create_provider()

    assert calls == [
        ("stt", {"model": "nova-3", "api_key": "dg-key"}),
        ("tts", {"voice": "thalia", "model": "aura-2-thalia-en", "api_key": "dg-key"}),
    ]


@pytest.mark.unit
def test_adapter_factories_read_gemini_and_deepgram_settings() -> None:
    inserted_paths = add_repo_paths()

    try:
        llm_module = load_module("agent_llm_pipeline", "app/pipeline/llm.py")
        stt_module = load_module("agent_stt_pipeline", "app/pipeline/stt.py")
        tts_module = load_module("agent_tts_pipeline", "app/pipeline/tts.py")
        settings = SimpleNamespace(
            llm_provider="gemini",
            llm_model="gemini-3-flash-preview",
            gemini_api_key="gemini-key",
            openai_api_key=None,
            stt_provider="deepgram",
            stt_model="nova-3",
            tts_provider="deepgram",
            tts_model="aura-2-thalia-en",
            tts_voice="thalia",
            deepgram_api_key="deepgram-key",
        )

        llm_adapter = llm_module.LlmAdapter.from_settings(settings)
        stt_adapter = stt_module.SttAdapter.from_settings(settings)
        tts_adapter = tts_module.TtsAdapter.from_settings(settings)

        assert llm_adapter.api_key == "gemini-key"
        assert stt_adapter.api_key == "deepgram-key"
        assert tts_adapter.voice == "thalia"
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_turn_pipeline_uses_no_answer_when_retrieval_misses() -> None:
    inserted_paths = add_repo_paths()

    try:
        turns_module = load_module("agent_turns_pipeline_unit", "app/pipeline/turns.py")
        from app.dialog.conversation import ConversationState
        from app.transcripts import TranscriptRecorder
        from cozmo_contracts.runtime import AgentRuntimeConfig

        class FakeTranscriptSink:
            def __init__(self) -> None:
                self.turns = []

            def append_transcript_turn(self, turn):
                self.turns.append(turn)
                return turn

            def next_turn_index(self, room_name: str) -> int:
                return 0

            def mark_transcript_turn_interrupted(self, room_name: str, turn_index: int):
                return None

        class FakeSttClient:
            async def transcribe(self, audio_input):
                return "Can you confirm pricing?"

        class FakeLlmClient:
            async def complete(self, chat_ctx):
                raise AssertionError("LLM should not be called when retrieval misses")

        class FakeTtsClient:
            async def synthesize(self, chunks):
                return tuple(chunk.text for chunk in chunks)

        runtime_config = AgentRuntimeConfig(
            config_id="main-inbound",
            did="+16625640501",
            agent_name="Main Reception",
            persona_prompt="Be concise and grounded.",
            kb_collection="main-faq",
            llm_provider="gemini",
            llm_model="gemini-3-flash-preview",
            tts_provider="deepgram",
            tts_model="aura-2-thalia-en",
            tts_voice="thalia",
            escalation_triggers=["human"],
        )
        recorder = TranscriptRecorder.from_sink(
            room_name="call-+16625640501-a1b2",
            sink=FakeTranscriptSink(),
        )
        pipeline = turns_module.TurnPipeline(
            runtime_config=runtime_config,
            conversation=ConversationState(),
            stt_client=FakeSttClient(),
            llm_client=FakeLlmClient(),
            tts_client=FakeTtsClient(),
            worker_name="cozmo-agent-1",
            transcript_recorder=recorder,
        )

        result = await pipeline.run_audio_turn(
            b"audio",
            knowledge_chunks=(),
            retrieval_attempted=True,
        )

        assert result.route == "no_answer"
        assert "grounded information" in result.agent_text
    finally:
        remove_repo_paths(*inserted_paths)
