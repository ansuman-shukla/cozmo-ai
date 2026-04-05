import asyncio
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
            or name in {"agent_job_module", "agent_metrics_module", "livekit"}
        ):
            sys.modules.pop(name, None)


class FakePublication:
    sid = "PUB_123"


class FakeLocalParticipant:
    def __init__(self) -> None:
        self.identity = "agent-local"
        self.attributes = {}
        self.metadata = None
        self.unpublished_sid = None

    async def publish_track(self, track):
        self.track = track
        return FakePublication()

    async def unpublish_track(self, sid: str) -> None:
        self.unpublished_sid = sid

    async def set_attributes(self, attributes):
        self.attributes = dict(attributes)

    async def set_metadata(self, metadata: str) -> None:
        self.metadata = metadata


class FakeRoom:
    def __init__(self) -> None:
        self.name = "call-+16625640501-a1b2"
        self.local_participant = FakeLocalParticipant()
        self.handlers = {}

    def on(self, event: str, callback) -> None:
        self.handlers.setdefault(event, []).append(callback)

    def emit(self, event: str, *args) -> None:
        for callback in self.handlers.get(event, []):
            callback(*args)


class FakeAudioSource:
    room = None
    instances = []

    def __init__(self, sample_rate: int, num_channels: int, queue_size_ms: int = 0) -> None:
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.queue_size_ms = queue_size_ms
        self.frames = []
        self.cleared = False
        self.waited = False
        FakeAudioSource.instances.append(self)

    async def capture_frame(self, frame) -> None:
        self.frames.append(frame)
        if len(self.frames) == 1 and FakeAudioSource.room is not None:
            FakeAudioSource.room.emit(
                "active_speakers_changed",
                [SimpleNamespace(identity="sip-caller-1")],
            )

    async def wait_for_playout(self) -> None:
        self.waited = True

    def clear_queue(self) -> None:
        self.cleared = True

    async def aclose(self) -> None:
        return None


class FakeLocalAudioTrack:
    @classmethod
    def create_audio_track(cls, name: str, source: FakeAudioSource):
        return SimpleNamespace(name=name, source=source)


class FakeAudioFrame:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class FakeTranscriptRepository:
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
                    interrupted=True,
                    created_at=1710000000.0,
                    metrics={"llm_node_ttft": 0.25, "tts_node_ttfb": 0.35, "e2e_latency": 0.8},
                )
            ),
        )
        self.emit(
            "close",
            SimpleNamespace(reason=SimpleNamespace(value="participant_disconnected"), error=None),
        )
        return FakeSpeechHandle(interrupted=True)

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


def counter_value(counter, **labels) -> float:
    for metric in counter.collect():
        for sample in metric.samples:
            if not sample.name.endswith("_total"):
                continue
            if sample.labels == labels:
                return sample.value
    return 0.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bootstrap_job_interrupts_greeting_and_marks_turn() -> None:
    inserted_paths = add_repo_paths()

    try:
        livekit_module = ModuleType("livekit")
        livekit_module.rtc = SimpleNamespace(
            ParticipantKind=SimpleNamespace(PARTICIPANT_KIND_SIP="SIP"),
        )
        agents_module = ModuleType("livekit.agents")
        agents_module.AutoSubscribe = SimpleNamespace(AUDIO_ONLY="audio_only")
        agents_module.room_io = SimpleNamespace(
            RoomOptions=lambda **kwargs: SimpleNamespace(**kwargs)
        )
        livekit_module.agents = agents_module
        sys.modules["livekit"] = livekit_module
        sys.modules["livekit.agents"] = agents_module

        job = load_module("agent_job_module", "app/job.py")
        metrics_module = load_module("agent_metrics_module", "app/observability/metrics.py")
        from app.bootstrap import ResolvedCallContext
        from cozmo_contracts.models import AgentConfigRecord
        from cozmo_contracts.runtime import RetrievalSettings, TimeoutSettings

        transcript_repository = FakeTranscriptRepository()
        room = FakeRoom()
        fake_session = FakeSession()
        settings = SimpleNamespace(
            worker_name="cozmo-agent-1",
            mongo_database="cozmo",
            room_quality_poll_interval_ms=5000,
            max_history_turns=10,
            llm_provider="gemini",
            llm_model="gemini-3-flash-preview",
            tts_provider="deepgram",
            tts_model="aura-2-thalia-en",
            tts_voice="thalia",
            retrieval_settings=lambda: RetrievalSettings(),
            timeout_settings=lambda: TimeoutSettings(),
        )
        ctx = SimpleNamespace(
            room=room,
            connect=lambda **kwargs: None,
            wait_for_participant=lambda **kwargs: SimpleNamespace(
                attributes={
                    "sip.trunkPhoneNumber": "+16625640501",
                    "sip.phoneNumber": "+919262561716",
                    "sip.twilio.callSid": "CA123",
                },
                identity="sip-caller-1",
                kind="SIP",
            ),
        )

        async def fake_connect(**kwargs):
            return None

        async def fake_wait_for_participant(**kwargs):
            return SimpleNamespace(
                attributes={
                    "sip.trunkPhoneNumber": "+16625640501",
                    "sip.phoneNumber": "+919262561716",
                    "sip.twilio.callSid": "CA123",
                },
                identity="sip-caller-1",
                kind="SIP",
            )

        ctx.connect = fake_connect
        ctx.wait_for_participant = fake_wait_for_participant

        agent_config = AgentConfigRecord(
            config_id="main-inbound",
            did="+16625640501",
            agent_name="Main Reception",
            persona_prompt="Be concise and helpful.",
            kb_collection="main-faq",
            llm_provider="gemini",
            llm_model="gemini-3-flash-preview",
            tts_provider="deepgram",
            tts_model="aura-2-thalia-en",
            tts_voice="thalia",
            escalation_triggers=["human"],
        )

        def fake_resolve_call_context(**kwargs):
            return ResolvedCallContext(
                room_name="call-+16625640501-a1b2",
                did="+16625640501",
                ani="+919262561716",
                provider_call_id="CA123",
                livekit_call_id="lk-call-1",
                participant_identity="sip-caller-1",
                agent_config=agent_config,
            )

        async def fake_wait_for_room_disconnect(room):
            return None

        job.resolve_call_context = fake_resolve_call_context
        job._wait_for_room_disconnect = fake_wait_for_room_disconnect
        job.MongoTranscriptStore.from_connection = classmethod(
            lambda cls, **kwargs: SimpleNamespace(repository=transcript_repository)
        )
        job._create_live_agent_session = lambda settings: fake_session
        job._build_live_agent = lambda runtime_config: {"instructions": "stub"}

        class FakeQualityMonitor:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

            async def run(self) -> None:
                await asyncio.Future()

        job.RoomQualityMonitor = FakeQualityMonitor

        before_interrupts = counter_value(
            metrics_module.RESPONSE_INTERRUPTS,
            worker_name="cozmo-agent-1",
            reason="caller_speech",
        )
        before_interrupted_turns = counter_value(
            metrics_module.INTERRUPTED_AGENT_TURNS,
            worker_name="cozmo-agent-1",
            agent_config_id="main-inbound",
        )

        await job._bootstrap_job(
            ctx,
            settings=settings,
            store=SimpleNamespace(client=object(), repository=object()),
            transcript_store=SimpleNamespace(repository=transcript_repository),
            dead_letter_store=SimpleNamespace(repository=object()),
            call_state_store=SimpleNamespace(repository=object()),
        )

        after_interrupts = counter_value(
            metrics_module.RESPONSE_INTERRUPTS,
            worker_name="cozmo-agent-1",
            reason="caller_speech",
        )
        after_interrupted_turns = counter_value(
            metrics_module.INTERRUPTED_AGENT_TURNS,
            worker_name="cozmo-agent-1",
            agent_config_id="main-inbound",
        )

        assert fake_session.started["room"] is room
        assert fake_session.started["room_options"].participant_identity == "sip-caller-1"
        assert fake_session.say_calls == [
            ("Hello, you've reached Main Reception. How can I help you today?", True)
        ]
        assert len(transcript_repository.turns) == 1
        assert transcript_repository.turns[0].speaker.value == "agent"
        assert transcript_repository.turns[0].interrupted is True
        assert after_interrupts == before_interrupts + 1
        assert after_interrupted_turns == before_interrupted_turns + 1
    finally:
        remove_repo_paths(*inserted_paths)
