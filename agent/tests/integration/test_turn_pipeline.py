from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

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
            or name in {"agent_turns_pipeline", "agent_metrics_module"}
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


class FakeSttClient:
    async def transcribe(self, audio_input) -> str:
        assert audio_input == b"audio-frame-payload"
        return "I need pricing details"


class FakeSequentialSttClient:
    def __init__(self, transcripts):
        self.transcripts = list(transcripts)

    async def transcribe(self, audio_input) -> str:
        assert audio_input == b"audio-frame-payload"
        return self.transcripts.pop(0)


class FakeLlmClient:
    async def complete(self, chat_ctx):
        from app.pipeline.llm import LlmResponse

        messages = chat_ctx.messages()
        assert messages[-1].role == "user"
        return LlmResponse(
            text="The starter plan is 29 dollars per month and annual billing is discounted.",
            provider="gemini",
            model="gemini-3-flash-preview",
        )


class FakeSequentialLlmClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.roles_seen = []

    async def complete(self, chat_ctx):
        from app.pipeline.llm import LlmResponse

        messages = chat_ctx.messages()
        self.roles_seen.append([message.role for message in messages])
        return LlmResponse(
            text=self.responses.pop(0),
            provider="gemini",
            model="gemini-3-flash-preview",
        )


class FakeTtsClient:
    def __init__(self) -> None:
        self.chunks = []

    async def synthesize(self, chunks):
        self.chunks = [chunk.text for chunk in chunks]
        return b"pcm-placeholder"


class FakeInterruptingTtsClient:
    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator
        self.chunk_texts = []
        self.turn_index = 0

    async def synthesize(self, chunks):
        return tuple(chunk.text for chunk in chunks)

    async def synthesize_chunk(self, chunk):
        self.chunk_texts.append((self.turn_index, chunk.text))
        if self.turn_index == 0:
            self.coordinator.interrupt("caller_speech")
        return f"chunk:{chunk.text}"

    def next_turn(self) -> None:
        self.turn_index += 1


class FakeTransferService:
    def __init__(self, *, should_succeed: bool = True) -> None:
        self.should_succeed = should_succeed
        self.requests = []

    async def transfer(self, request):
        from app.dialog.transfer import TransferOutcome, build_transfer_success_response
        from app.dialog.fallbacks import build_transfer_failure_response

        self.requests.append(request)
        if self.should_succeed:
            return TransferOutcome(
                success=True,
                transfer_target=request.transfer_target,
                message=build_transfer_success_response(request.transfer_target),
            )
        return TransferOutcome(
            success=False,
            transfer_target=request.transfer_target,
            message=build_transfer_failure_response(),
        )


class FakeCallStateSink:
    def __init__(self) -> None:
        self.marked = []

    def mark_transferred(self, room_name: str, transfer_target: str):
        self.marked.append((room_name, transfer_target))
        return {"room_name": room_name, "transfer_target": transfer_target}


def histogram_count(histogram, *, worker_name: str, agent_config_id: str, stage: str) -> float:
    for metric in histogram.collect():
        for sample in metric.samples:
            if not sample.name.endswith("_count"):
                continue
            if sample.labels == {
                "worker_name": worker_name,
                "agent_config_id": agent_config_id,
                "stage": stage,
            }:
                return sample.value
    return 0.0


def counter_total(counter, **labels) -> float:
    for metric in counter.collect():
        for sample in metric.samples:
            if not sample.name.endswith("_total"):
                continue
            if sample.labels == labels:
                return sample.value
    return 0.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_turn_pipeline_runs_mocked_audio_roundtrip_and_records_metrics() -> None:
    inserted_paths = add_repo_paths()

    try:
        turns_module = load_module("agent_turns_pipeline", "app/pipeline/turns.py")
        metrics_module = load_module("agent_metrics_module", "app/observability/metrics.py")
        from app.dialog.conversation import ConversationState
        from app.pipeline.rag import RetrievedChunk
        from app.transcripts import TranscriptRecorder
        from cozmo_contracts.runtime import AgentRuntimeConfig

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
        transcript_sink = FakeTranscriptSink()
        recorder = TranscriptRecorder.from_sink(
            room_name="call-+16625640501-a1b2",
            sink=transcript_sink,
        )
        tts_client = FakeTtsClient()
        pipeline = turns_module.TurnPipeline(
            runtime_config=runtime_config,
            conversation=ConversationState(),
            stt_client=FakeSttClient(),
            llm_client=FakeLlmClient(),
            tts_client=tts_client,
            worker_name="cozmo-agent-1",
            transcript_recorder=recorder,
        )

        before = histogram_count(
            metrics_module.TURN_LATENCY_MS,
            worker_name="cozmo-agent-1",
            agent_config_id="main-inbound",
            stage="pipeline_rtt_ms",
        )
        result = await pipeline.run_audio_turn(
            b"audio-frame-payload",
            knowledge_chunks=(
                RetrievedChunk(
                    chunk_id="pricing-1",
                    text="The starter plan begins at 29 dollars per month.",
                    score=0.91,
                ),
            ),
        )
        after = histogram_count(
            metrics_module.TURN_LATENCY_MS,
            worker_name="cozmo-agent-1",
            agent_config_id="main-inbound",
            stage="pipeline_rtt_ms",
        )

        assert result.user_text == "I need pricing details"
        assert "29 dollars per month" in result.agent_text
        assert tts_client.chunks == [
            "The starter plan is 29 dollars per month and annual billing is discounted."
        ]
        assert [turn.speaker.value for turn in transcript_sink.turns] == ["user", "agent"]
        assert [turn.turn_index for turn in transcript_sink.turns] == [0, 1]
        assert transcript_sink.turns[1].kb_chunks_used[0].chunk_id == "pricing-1"
        assert result.latency.pipeline_rtt_ms is not None
        assert after == before + 1
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_turn_pipeline_processes_next_user_turn_after_interruption() -> None:
    inserted_paths = add_repo_paths()

    try:
        turns_module = load_module("agent_turns_pipeline", "app/pipeline/turns.py")
        metrics_module = load_module("agent_metrics_module", "app/observability/metrics.py")
        from app.dialog.conversation import ConversationState
        from app.pipeline.interruption import InterruptionCoordinator
        from app.transcripts import TranscriptRecorder
        from cozmo_contracts.runtime import AgentRuntimeConfig

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
        transcript_sink = FakeTranscriptSink()
        recorder = TranscriptRecorder.from_sink(
            room_name="call-+16625640501-a1b2",
            sink=transcript_sink,
        )
        coordinator = InterruptionCoordinator()
        stt_client = FakeSequentialSttClient(
            [
                "Tell me about pricing",
                "Okay, what about annual billing?",
            ]
        )
        llm_client = FakeSequentialLlmClient(
            [
                "The starter plan is 29 dollars per month. We also offer annual billing discounts.",
                "Annual billing saves about 15 percent compared with monthly billing.",
            ]
        )
        tts_client = FakeInterruptingTtsClient(coordinator)
        pipeline = turns_module.TurnPipeline(
            runtime_config=runtime_config,
            conversation=ConversationState(),
            stt_client=stt_client,
            llm_client=llm_client,
            tts_client=tts_client,
            worker_name="cozmo-agent-1",
            transcript_recorder=recorder,
            interruption_coordinator=coordinator,
        )

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

        first = await pipeline.run_audio_turn(b"audio-frame-payload")
        tts_client.next_turn()
        second = await pipeline.run_audio_turn(b"audio-frame-payload")

        after_interrupts = counter_total(
            metrics_module.RESPONSE_INTERRUPTS,
            worker_name="cozmo-agent-1",
            reason="caller_speech",
        )
        after_interrupted_turns = counter_total(
            metrics_module.INTERRUPTED_AGENT_TURNS,
            worker_name="cozmo-agent-1",
            agent_config_id="main-inbound",
        )

        assert first.interrupted is True
        assert first.interruption_reason == "caller_speech"
        assert second.interrupted is False
        assert "15 percent" in second.agent_text
        assert [turn.speaker.value for turn in transcript_sink.turns] == ["user", "agent", "user", "agent"]
        assert [turn.interrupted for turn in transcript_sink.turns] == [False, True, False, False]
        assert [turn.turn_index for turn in transcript_sink.turns] == [0, 1, 2, 3]
        assert [turn.speaker for turn in pipeline.conversation.turns] == ["user", "agent", "user", "agent"]
        assert pipeline.conversation.turns[1].interrupted is True
        assert pipeline.conversation.turns[3].interrupted is False
        assert llm_client.roles_seen[1] == ["system", "user", "assistant", "user"]
        assert after_interrupts == before_interrupts + 1
        assert after_interrupted_turns == before_interrupted_turns + 1
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_turn_pipeline_runs_scripted_objection_scenario_end_to_end() -> None:
    inserted_paths = add_repo_paths()

    try:
        turns_module = load_module("agent_turns_pipeline", "app/pipeline/turns.py")
        from app.dialog.conversation import ConversationState
        from app.transcripts import TranscriptRecorder
        from cozmo_contracts.runtime import AgentRuntimeConfig

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
        transcript_sink = FakeTranscriptSink()
        recorder = TranscriptRecorder.from_sink(
            room_name="call-+16625640501-a1b2",
            sink=transcript_sink,
        )
        pipeline = turns_module.TurnPipeline(
            runtime_config=runtime_config,
            conversation=ConversationState(),
            stt_client=FakeSequentialSttClient(["I don't believe this is real."]),
            llm_client=FakeSequentialLlmClient([]),
            tts_client=FakeTtsClient(),
            worker_name="cozmo-agent-1",
            transcript_recorder=recorder,
        )

        result = await pipeline.run_audio_turn(b"audio-frame-payload")

        assert result.route == "scripted"
        assert result.objection_type == "trust"
        assert "connect you with a human" in result.agent_text
        assert [turn.objection_type for turn in transcript_sink.turns] == ["trust", None]
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_turn_pipeline_marks_transfer_state_on_success() -> None:
    inserted_paths = add_repo_paths()

    try:
        turns_module = load_module("agent_turns_pipeline", "app/pipeline/turns.py")
        from app.dialog.conversation import ConversationState
        from app.transcripts import TranscriptRecorder
        from cozmo_contracts.runtime import AgentRuntimeConfig

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
            transfer_target="sip:frontdesk@pbx.example.com",
        )
        transcript_sink = FakeTranscriptSink()
        recorder = TranscriptRecorder.from_sink(
            room_name="call-+16625640501-a1b2",
            sink=transcript_sink,
        )
        transfer_service = FakeTransferService(should_succeed=True)
        call_state_sink = FakeCallStateSink()
        pipeline = turns_module.TurnPipeline(
            runtime_config=runtime_config,
            conversation=ConversationState(),
            stt_client=FakeSequentialSttClient(["Please transfer me to a human."]),
            llm_client=FakeSequentialLlmClient([]),
            tts_client=FakeTtsClient(),
            worker_name="cozmo-agent-1",
            transcript_recorder=recorder,
            transfer_service=transfer_service,
            call_state_sink=call_state_sink,
            room_name="call-+16625640501-a1b2",
            provider_call_id="CA123",
            ani="+919262561716",
        )

        result = await pipeline.run_audio_turn(b"audio-frame-payload")

        assert result.route == "transfer"
        assert result.transfer_outcome is not None and result.transfer_outcome.success is True
        assert transfer_service.requests[0].transfer_target == "sip:frontdesk@pbx.example.com"
        assert call_state_sink.marked == [
            ("call-+16625640501-a1b2", "sip:frontdesk@pbx.example.com")
        ]
        assert "connect you to sip:frontdesk@pbx.example.com" in result.agent_text
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_turn_pipeline_falls_back_gracefully_when_transfer_fails() -> None:
    inserted_paths = add_repo_paths()

    try:
        turns_module = load_module("agent_turns_pipeline", "app/pipeline/turns.py")
        from app.dialog.conversation import ConversationState
        from app.transcripts import TranscriptRecorder
        from cozmo_contracts.runtime import AgentRuntimeConfig

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
            transfer_target="sip:frontdesk@pbx.example.com",
        )
        transcript_sink = FakeTranscriptSink()
        recorder = TranscriptRecorder.from_sink(
            room_name="call-+16625640501-a1b2",
            sink=transcript_sink,
        )
        transfer_service = FakeTransferService(should_succeed=False)
        call_state_sink = FakeCallStateSink()
        pipeline = turns_module.TurnPipeline(
            runtime_config=runtime_config,
            conversation=ConversationState(),
            stt_client=FakeSequentialSttClient(["I want a manager right now."]),
            llm_client=FakeSequentialLlmClient([]),
            tts_client=FakeTtsClient(),
            worker_name="cozmo-agent-1",
            transcript_recorder=recorder,
            transfer_service=transfer_service,
            call_state_sink=call_state_sink,
            room_name="call-+16625640501-a1b2",
        )

        result = await pipeline.run_audio_turn(b"audio-frame-payload")

        assert result.route == "transfer_failed"
        assert result.transfer_outcome is not None and result.transfer_outcome.success is False
        assert "couldn't complete the transfer" in result.agent_text
        assert call_state_sink.marked == []
        assert [turn.turn_index for turn in transcript_sink.turns] == [0, 1]
    finally:
        remove_repo_paths(*inserted_paths)
