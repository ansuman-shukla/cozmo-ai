from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

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
            or name.startswith("livekit")
            or name.startswith("agent_live_")
        ):
            sys.modules.pop(name, None)


class FakeTranscriptSink:
    def __init__(self) -> None:
        self.turns = []

    def append_transcript_turn(self, turn):
        self.turns.append(turn)
        return turn

    def next_turn_index(self, room_name: str) -> int:
        return 0

    def mark_transcript_turn_interrupted(self, room_name: str, turn_index: int):
        for turn in self.turns:
            if turn.room_name == room_name and turn.turn_index == turn_index:
                turn.interrupted = True
                return turn
        return None


class FakeSession:
    def __init__(self) -> None:
        self.handlers = {}
        self.started = None
        self.say_calls = []
        self.closed = False

    def on(self, event: str, callback) -> None:
        self.handlers[event] = callback

    def emit(self, event: str, payload) -> None:
        callback = self.handlers.get(event)
        if callback is not None:
            callback(payload)

    async def start(self, agent, *, room, room_options, record) -> None:
        self.started = {
            "agent": agent,
            "room": room,
            "room_options": room_options,
            "record": record,
        }

    def say(self, text: str, *, add_to_chat_ctx: bool = True):
        self.say_calls.append((text, add_to_chat_ctx))
        self.emit(
            "conversation_item_added",
            SimpleNamespace(
                item=SimpleNamespace(
                    id="assistant-greeting",
                    role="assistant",
                    text_content=text,
                    interrupted=False,
                    created_at=1710000000.0,
                    metrics={"llm_node_ttft": 0.25, "tts_node_ttfb": 0.35, "e2e_latency": 0.8},
                )
            ),
        )
        self.emit(
            "close",
            SimpleNamespace(reason=SimpleNamespace(value="participant_disconnected"), error=None),
        )
        return FakeSpeechHandle(interrupted=False)

    async def aclose(self) -> None:
        self.closed = True


class FakeSpeechHandle:
    def __init__(self, *, interrupted: bool) -> None:
        self.interrupted = interrupted

    async def wait_for_playout(self):
        return None

    def __await__(self):
        async def _await_impl():
            await self.wait_for_playout()
            return self

        return _await_impl().__await__()


class FakeRoom:
    def __init__(self) -> None:
        self.handlers = {}

    def on(self, event: str, callback) -> None:
        self.handlers[event] = callback


def counter_total(counter, **labels) -> float:
    for metric in counter.collect():
        for sample in metric.samples:
            if not sample.name.endswith("_total"):
                continue
            if sample.labels == labels:
                return sample.value
    return 0.0


@pytest.mark.unit
def test_build_runtime_config_uses_env_selected_live_providers() -> None:
    inserted_paths = add_repo_paths()

    try:
        job = load_module("agent_live_job_module", "app/job.py")
        from cozmo_contracts.models import AgentConfigRecord
        from cozmo_contracts.runtime import RetrievalSettings, TimeoutSettings

        settings = SimpleNamespace(
            max_history_turns=12,
            llm_provider="gemini",
            llm_model="gemini-3-flash-preview",
            tts_provider="deepgram",
            tts_model="aura-2-thalia-en",
            tts_voice="thalia",
            retrieval_settings=lambda: RetrievalSettings(top_k=4, min_score=0.4),
            timeout_settings=lambda: TimeoutSettings(stt_ms=4000, llm_ms=6000, tts_ms=4500, kb_ms=200),
        )
        resolved = SimpleNamespace(
            agent_config=AgentConfigRecord(
                config_id="main-inbound",
                did="+16625640501",
                agent_name="Main Reception",
                persona_prompt="Be concise and helpful on the phone.",
                kb_collection="main-faq",
                llm_provider="openai",
                llm_model="gpt-4o-mini",
                tts_provider="other",
                tts_model="legacy-voice",
                tts_voice="legacy",
                escalation_triggers=["human"],
                active=True,
            )
        )

        runtime = job._build_runtime_config(settings, resolved=resolved)

        assert runtime.llm_provider == "gemini"
        assert runtime.llm_model == "gemini-3-flash-preview"
        assert runtime.tts_provider == "deepgram"
        assert runtime.tts_model == "aura-2-thalia-en"
        assert runtime.tts_voice == "thalia"
        assert runtime.retrieval.top_k == 4
        assert runtime.timeouts.llm_ms == 6000
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_live_session_handlers_persist_messages_and_interruption_metrics() -> None:
    inserted_paths = add_repo_paths()

    try:
        metrics_module = load_module("agent_live_metrics_module", "app/observability/metrics.py")
        job = load_module("agent_live_job_module", "app/job.py")
        from app.transcripts import TranscriptRecorder
        from cozmo_contracts.runtime import AgentRuntimeConfig

        sink = FakeTranscriptSink()
        recorder = TranscriptRecorder.from_sink(room_name="call-1", sink=sink)
        session = FakeSession()
        controller = job.LiveSessionController()
        runtime_config = AgentRuntimeConfig(
            config_id="main-inbound",
            did="+16625640501",
            agent_name="Main Reception",
            persona_prompt="Be concise and helpful on the phone.",
            kb_collection="main-faq",
            llm_provider="gemini",
            llm_model="gemini-3-flash-preview",
            tts_provider="deepgram",
            tts_model="aura-2-thalia-en",
            tts_voice="thalia",
            escalation_triggers=["human"],
        )
        settings = SimpleNamespace(worker_name="cozmo-agent-1")
        before_interrupts = counter_total(
            metrics_module.RESPONSE_INTERRUPTS,
            worker_name="cozmo-agent-1",
            reason="caller_speech",
        )
        before_interrupted_turns = counter_total(
            metrics_module.INTERRUPTED_AGENT_TURNS,
            worker_name="cozmo-agent-1",
            agent_config_id="main-inbound",
        )

        job._install_live_session_handlers(
            session,
            controller=controller,
            recorder=recorder,
            settings=settings,
            runtime_config=runtime_config,
        )

        session.emit(
            "conversation_item_added",
            SimpleNamespace(
                item=SimpleNamespace(
                    id="user-1",
                    role="user",
                    text_content="I need pricing details",
                    interrupted=False,
                    created_at=1710000000.0,
                    metrics={"transcription_delay": 0.22, "end_of_turn_delay": 0.11},
                )
            ),
        )
        session.emit(
            "conversation_item_added",
            SimpleNamespace(
                item=SimpleNamespace(
                    id="assistant-1",
                    role="assistant",
                    text_content="The starter plan is 29 dollars per month.",
                    interrupted=True,
                    created_at=1710000001.0,
                    metrics={"llm_node_ttft": 0.31, "tts_node_ttfb": 0.42, "e2e_latency": 0.95},
                )
            ),
        )
        await controller.drain()

        assert [turn.speaker.value for turn in sink.turns] == ["user", "agent"]
        assert sink.turns[0].latency.stt_ms == pytest.approx(220.0)
        assert sink.turns[0].latency.endpoint_ms == pytest.approx(110.0)
        assert sink.turns[1].interrupted is True
        assert sink.turns[1].latency.llm_ttft_ms == pytest.approx(310.0)
        assert sink.turns[1].latency.tts_first_audio_ms == pytest.approx(420.0)
        assert counter_total(
            metrics_module.RESPONSE_INTERRUPTS,
            worker_name="cozmo-agent-1",
            reason="caller_speech",
        ) == before_interrupts + 1
        assert counter_total(
            metrics_module.INTERRUPTED_AGENT_TURNS,
            worker_name="cozmo-agent-1",
            agent_config_id="main-inbound",
        ) == before_interrupted_turns + 1
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_live_agent_loop_starts_session_and_publishes_greeting(monkeypatch) -> None:
    inserted_paths = add_repo_paths()

    try:
        livekit_module = ModuleType("livekit")
        livekit_agents_module = ModuleType("livekit.agents")

        class FakeRoomOptions:
            def __init__(self, **kwargs) -> None:
                self.__dict__.update(kwargs)

        livekit_agents_module.room_io = SimpleNamespace(RoomOptions=FakeRoomOptions)
        livekit_module.agents = livekit_agents_module
        sys.modules["livekit"] = livekit_module
        sys.modules["livekit.agents"] = livekit_agents_module

        job = load_module("agent_live_job_module", "app/job.py")
        from app.transcripts import TranscriptRecorder
        from cozmo_contracts.models import AgentConfigRecord
        from cozmo_contracts.runtime import RetrievalSettings, TimeoutSettings

        fake_session = FakeSession()
        monkeypatch.setattr(job, "_create_live_agent_session", lambda settings: fake_session)
        monkeypatch.setattr(job, "_build_live_agent", lambda runtime_config: {"instructions": "stub"})

        settings = SimpleNamespace(
            worker_name="cozmo-agent-1",
            llm_provider="gemini",
            llm_model="gemini-3-flash-preview",
            tts_provider="deepgram",
            tts_model="aura-2-thalia-en",
            tts_voice="thalia",
            max_history_turns=10,
            retrieval_settings=lambda: RetrievalSettings(),
            timeout_settings=lambda: TimeoutSettings(),
        )
        resolved = SimpleNamespace(
            room_name="call-+16625640501-a1b2",
            agent_config=AgentConfigRecord(
                config_id="main-inbound",
                did="+16625640501",
                agent_name="Main Reception",
                persona_prompt="Be concise and helpful on the phone.",
                kb_collection="main-faq",
                llm_provider="openai",
                llm_model="legacy",
                tts_provider="legacy",
                tts_model="legacy",
                tts_voice="legacy",
                escalation_triggers=["human"],
                active=True,
            ),
        )
        sink = FakeTranscriptSink()
        recorder = TranscriptRecorder.from_sink(room_name=resolved.room_name, sink=sink)
        ctx = SimpleNamespace(room=FakeRoom())

        await job._run_live_agent_loop(
            ctx,
            settings=settings,
            resolved=resolved,
            transcript_recorder=recorder,
            participant_identity="sip-caller-1",
        )

        assert fake_session.started["room"] is ctx.room
        assert fake_session.started["record"] is False
        assert fake_session.started["room_options"].text_input is False
        assert fake_session.started["room_options"].participant_identity == "sip-caller-1"
        assert fake_session.say_calls == [
            ("Hello, you've reached Main Reception. How can I help you today?", True)
        ]
        assert [turn.speaker.value for turn in sink.turns] == ["agent"]
        assert sink.turns[0].text == "Hello, you've reached Main Reception. How can I help you today?"
        assert fake_session.closed is True
    finally:
        remove_repo_paths(*inserted_paths)
