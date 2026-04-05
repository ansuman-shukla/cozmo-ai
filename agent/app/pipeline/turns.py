"""Per-turn speech pipeline orchestration helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import inspect
from time import perf_counter
from typing import Any, Protocol, Sequence

from cozmo_contracts.models import TurnLatencyMetrics
from cozmo_contracts.runtime import AgentRuntimeConfig

from app.call_state import CallStateSink
from app.dialog.conversation import ConversationState
from app.dialog.fallbacks import (
    build_no_answer_response,
    build_transfer_failure_response,
    should_use_no_answer_fallback,
)
from app.dialog.objection_handler import ObjectionDecision, ObjectionHandler, ObjectionRoute
from app.dialog.transfer import (
    TransferOutcome,
    TransferRequestBuilder,
    TransferService,
    build_transfer_success_response,
)
from app.observability.metrics import (
    calculate_perceived_rtt_ms,
    calculate_pipeline_rtt_ms,
    record_interrupted_agent_turn,
    record_response_interrupt,
    record_turn_latency_metrics,
)
from app.pipeline.interruption import InterruptionCoordinator
from app.pipeline.llm import LlmResponse, PromptBuilder
from app.pipeline.rag import RetrievedChunk
from app.pipeline.tts import TtsChunk, TtsChunker
from app.transcripts import TranscriptRecorder


class SttClient(Protocol):
    """Protocol for mocked or real STT implementations used by the turn pipeline."""

    async def transcribe(self, audio_input: Any) -> str:
        """Return the caller transcript for one audio turn."""


class LlmClient(Protocol):
    """Protocol for mocked or real LLM implementations used by the turn pipeline."""

    async def complete(self, chat_ctx: Any) -> LlmResponse:
        """Return the agent response for the built chat context."""


class TtsClient(Protocol):
    """Protocol for mocked or real TTS implementations used by the turn pipeline."""

    async def synthesize(self, chunks: Sequence[TtsChunk]) -> Any:
        """Return provider output for the stable TTS text chunks."""


@dataclass(frozen=True, slots=True)
class TurnPipelineResult:
    """Normalized output from one end-to-end user turn."""

    user_text: str
    agent_text: str
    tts_chunks: tuple[TtsChunk, ...]
    tts_output: Any
    latency: TurnLatencyMetrics
    interrupted: bool = False
    interruption_reason: str | None = None
    route: str = "llm"
    objection_type: str | None = None
    transfer_outcome: TransferOutcome | None = None


async def _maybe_await(value: Any) -> Any:
    """Await values that may be sync or async depending on the test double."""

    if inspect.isawaitable(value):
        return await value
    return value


@dataclass(slots=True)
class TurnPipeline:
    """End-to-end turn orchestration for mocked-provider integration coverage."""

    runtime_config: AgentRuntimeConfig
    conversation: ConversationState
    stt_client: SttClient
    llm_client: LlmClient
    tts_client: TtsClient
    worker_name: str
    prompt_builder: PromptBuilder = field(default_factory=PromptBuilder)
    tts_chunker: TtsChunker = field(default_factory=TtsChunker)
    transcript_recorder: TranscriptRecorder | None = None
    interruption_coordinator: InterruptionCoordinator | None = None
    objection_handler: ObjectionHandler = field(default_factory=ObjectionHandler)
    transfer_request_builder: TransferRequestBuilder = field(default_factory=TransferRequestBuilder)
    transfer_service: TransferService | None = None
    call_state_sink: CallStateSink | None = None
    room_name: str | None = None
    provider_call_id: str | None = None
    ani: str | None = None

    async def _synthesize_tts(
        self,
        tts_chunks: tuple[TtsChunk, ...],
    ) -> tuple[Any, float, bool, str | None]:
        """Synthesize TTS with optional interruption-aware chunk playback."""

        tts_started = perf_counter()
        coordinator = self.interruption_coordinator

        if coordinator is None or not hasattr(self.tts_client, "synthesize_chunk"):
            tts_output = await _maybe_await(self.tts_client.synthesize(tts_chunks))
            return tts_output, (perf_counter() - tts_started) * 1000, False, None

        coordinator.begin_response()
        outputs: list[Any] = []
        first_audio_ms: float | None = None
        try:
            for chunk in tts_chunks:
                if coordinator.interrupted:
                    break
                coordinator.enqueue_output(chunk)
                next_chunk = coordinator.dequeue_output()
                if next_chunk is None:
                    break
                chunk_output = await _maybe_await(self.tts_client.synthesize_chunk(next_chunk))
                outputs.append(chunk_output)
                if first_audio_ms is None:
                    first_audio_ms = (perf_counter() - tts_started) * 1000
                if coordinator.interrupted:
                    break
        finally:
            interruption_reason = coordinator.interruption_reason
            interrupted = coordinator.interrupted
            coordinator.finish_response()

        return (
            tuple(outputs),
            first_audio_ms if first_audio_ms is not None else (perf_counter() - tts_started) * 1000,
            interrupted,
            interruption_reason,
        )

    async def run_audio_turn(
        self,
        audio_input: Any,
        *,
        knowledge_chunks: Sequence[RetrievedChunk] = (),
        retrieval_attempted: bool = False,
    ) -> TurnPipelineResult:
        """Run one audio-input turn through STT, LLM, transcript hooks, and TTS."""

        pipeline_started = perf_counter()

        stt_started = perf_counter()
        user_text = " ".join(str(await _maybe_await(self.stt_client.transcribe(audio_input))).split()).strip()
        stt_ms = (perf_counter() - stt_started) * 1000
        if not user_text:
            raise ValueError("STT returned an empty transcript")

        decision = self.objection_handler.classify(
            user_text,
            escalation_triggers=self.runtime_config.escalation_triggers,
        )

        chat_ctx = self.prompt_builder.build_chat_context(
            runtime_config=self.runtime_config,
            conversation=self.conversation,
            pending_user_text=user_text,
            knowledge_chunks=knowledge_chunks,
        )
        self.conversation.append("user", user_text)
        if self.transcript_recorder is not None:
            await asyncio.to_thread(
                self.transcript_recorder.record_user_turn,
                user_text,
                objection_type=decision.objection_type,
            )

        route = decision.route.value
        transfer_outcome: TransferOutcome | None = None
        llm_ttft_ms: float | None = None

        if decision.route == ObjectionRoute.SCRIPTED:
            agent_text = decision.scripted_response or build_no_answer_response(self.runtime_config)
        elif decision.route == ObjectionRoute.TRANSFER:
            if self.transfer_service is None:
                transfer_outcome = TransferOutcome(
                    success=False,
                    transfer_target=self.runtime_config.transfer_target or "",
                    message=build_transfer_failure_response(),
                )
                agent_text = transfer_outcome.message
            else:
                try:
                    request = self.transfer_request_builder.build(
                        runtime_config=self.runtime_config,
                        room_name=self.room_name or "call-session",
                        reason=user_text,
                        provider_call_id=self.provider_call_id,
                        did=self.runtime_config.did,
                        ani=self.ani,
                    )
                    transfer_outcome = await _maybe_await(self.transfer_service.transfer(request))
                except Exception:
                    transfer_outcome = TransferOutcome(
                        success=False,
                        transfer_target=self.runtime_config.transfer_target or "",
                        message=build_transfer_failure_response(),
                    )
                if transfer_outcome.success:
                    agent_text = transfer_outcome.message or build_transfer_success_response(
                        transfer_outcome.transfer_target
                    )
                    if self.call_state_sink is not None and self.room_name:
                        await asyncio.to_thread(
                            self.call_state_sink.mark_transferred,
                            self.room_name,
                            transfer_outcome.transfer_target,
                        )
                else:
                    agent_text = transfer_outcome.message or build_transfer_failure_response()
                    route = "transfer_failed"
        elif retrieval_attempted and should_use_no_answer_fallback(knowledge_chunks):
            agent_text = build_no_answer_response(self.runtime_config)
            route = "no_answer"
        else:
            llm_started = perf_counter()
            llm_response = await self.llm_client.complete(chat_ctx)
            llm_ttft_ms = (perf_counter() - llm_started) * 1000
            agent_text = " ".join(str(llm_response.text or "").split()).strip()
            if not agent_text:
                agent_text = build_no_answer_response(self.runtime_config)
                route = "no_answer"

        tts_chunks = tuple(self.tts_chunker.chunk(agent_text))
        tts_output, tts_first_audio_ms, interrupted, interruption_reason = await self._synthesize_tts(
            tts_chunks
        )

        self.conversation.append("agent", agent_text, interrupted=interrupted)
        pipeline_rtt_ms = calculate_pipeline_rtt_ms(
            stt_ms=stt_ms,
            llm_ttft_ms=llm_ttft_ms,
            tts_first_audio_ms=tts_first_audio_ms,
        )
        perceived_rtt_ms = calculate_perceived_rtt_ms(
            endpoint_ms=None,
            stt_ms=stt_ms,
            llm_ttft_ms=llm_ttft_ms,
            tts_first_audio_ms=tts_first_audio_ms,
        )
        latency = TurnLatencyMetrics(
            stt_ms=stt_ms,
            llm_ttft_ms=llm_ttft_ms,
            tts_first_audio_ms=tts_first_audio_ms,
            pipeline_rtt_ms=pipeline_rtt_ms or (perf_counter() - pipeline_started) * 1000,
            perceived_rtt_ms=perceived_rtt_ms,
        )

        if self.transcript_recorder is not None:
            await asyncio.to_thread(
                self.transcript_recorder.record_agent_turn,
                agent_text,
                interrupted=interrupted,
                latency=latency,
                kb_chunks_used=knowledge_chunks,
            )

        if interrupted:
            record_response_interrupt(
                self.worker_name,
                interruption_reason or "caller_speech",
            )
            record_interrupted_agent_turn(
                self.worker_name,
                self.runtime_config.config_id,
            )
        record_turn_latency_metrics(
            self.worker_name,
            self.runtime_config.config_id,
            latency,
        )
        return TurnPipelineResult(
            user_text=user_text,
            agent_text=agent_text,
            tts_chunks=tts_chunks,
            tts_output=tts_output,
            latency=latency,
            interrupted=interrupted,
            interruption_reason=interruption_reason,
            route=route,
            objection_type=decision.objection_type,
            transfer_outcome=transfer_outcome,
        )
