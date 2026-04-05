"""Per-call worker orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import logging
from time import perf_counter
from typing import Any

from cozmo_contracts.models import TurnLatencyMetrics
from cozmo_contracts.runtime import AgentRuntimeConfig

from app.call_state import MongoCallStateStore
from app.bootstrap import (
    AgentBootstrapError,
    MongoAgentConfigStore,
    build_agent_identity,
    resolve_call_context,
    room_name_matches_prefix,
)
from app.config import Settings, get_settings
from app.config import export_provider_environment
from app.observability.metrics import (
    calculate_perceived_rtt_ms,
    calculate_pipeline_rtt_ms,
    record_call_setup,
    record_greeting_publish,
    record_greeting_publish_failure,
    record_interrupted_agent_turn,
    record_job_finished,
    record_job_started,
    record_job_bootstrap,
    record_job_bootstrap_failure,
    record_recovery,
    record_response_interrupt,
    record_turn_latency_metrics,
    record_worker_start,
)
from app.observability.quality import RoomQualityMonitor
from app.observability.system import WorkerSystemMonitor
from app.pipeline.interruption import InterruptionCoordinator
from app.pipeline.llm import LlmAdapter, PromptBuilder
from app.pipeline.stt import SttAdapter
from app.pipeline.tts import PlaceholderGreetingRenderer, build_initial_greeting
from app.pipeline.tts import TtsAdapter
from app.recovery.rejoin import MongoRecoveryStore, RejoinCoordinator
from app.transcripts import (
    MongoTranscriptDeadLetterStore,
    MongoTranscriptStore,
    TranscriptRecorder,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class LiveSessionController:
    """Track async state for one live AgentSession."""

    close_event: asyncio.Event = field(default_factory=asyncio.Event)
    close_reason: str | None = None
    close_error: Any = None
    pending_tasks: set[asyncio.Task[Any]] = field(default_factory=set)

    def schedule(self, coroutine: Any) -> None:
        """Track a callback-driven coroutine spawned from a sync event handler."""

        task = asyncio.create_task(coroutine)
        self.pending_tasks.add(task)
        task.add_done_callback(self.pending_tasks.discard)

    async def drain(self) -> None:
        """Wait for all spawned callback tasks to finish."""

        if not self.pending_tasks:
            return
        await asyncio.gather(*tuple(self.pending_tasks), return_exceptions=True)


class GreetingPlaybackInterrupted(RuntimeError):
    """Raised when the initial greeting is interrupted by caller speech."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _wait_for_room_disconnect(room: Any) -> None:
    """Block until the LiveKit room disconnects."""

    disconnected = asyncio.Event()
    room.on("disconnected", lambda *_args, **_kwargs: disconnected.set())
    await disconnected.wait()


def _install_active_speaker_interruption_handler(
    room: Any,
    *,
    local_identity: str | None,
    coordinator: InterruptionCoordinator,
) -> None:
    """Interrupt active playback when a remote participant becomes an active speaker."""

    def on_active_speakers_changed(active_speakers: Any = None, *_args: Any, **_kwargs: Any) -> None:
        if not coordinator.response_active or coordinator.interrupted:
            return

        speakers = active_speakers if isinstance(active_speakers, (list, tuple, set)) else [active_speakers]
        for speaker in speakers:
            if speaker is None:
                continue
            identity = getattr(speaker, "identity", None)
            if identity and local_identity and identity == local_identity:
                continue
            coordinator.interrupt("caller_speech")
            return

    room.on("active_speakers_changed", on_active_speakers_changed)


async def _publish_greeting_audio(
    ctx: Any,
    *,
    settings: Settings,
    agent_name: str,
    agent_config_id: str,
    coordinator: InterruptionCoordinator,
) -> None:
    """Publish a short greeting-audio placeholder after bootstrap completes."""

    from livekit import rtc

    renderer = PlaceholderGreetingRenderer()
    rendered = renderer.synthesize(build_initial_greeting(agent_name))
    source = rtc.AudioSource(rendered.sample_rate, rendered.num_channels, queue_size_ms=200)
    track = rtc.LocalAudioTrack.create_audio_track("cozmo-greeting", source)
    publication = await ctx.room.local_participant.publish_track(track)
    _install_active_speaker_interruption_handler(
        ctx.room,
        local_identity=getattr(ctx.room.local_participant, "identity", None),
        coordinator=coordinator,
    )
    coordinator.begin_response()

    try:
        for frame_payload in rendered.iter_pcm_frames():
            coordinator.enqueue_output(frame_payload)

        while True:
            frame_payload = coordinator.dequeue_output()
            if frame_payload is None:
                break
            frame = rtc.AudioFrame(
                data=frame_payload,
                sample_rate=rendered.sample_rate,
                num_channels=rendered.num_channels,
                samples_per_channel=rendered.samples_per_frame,
            )
            await source.capture_frame(frame)

        if coordinator.interrupted:
            source.clear_queue()
            current_attributes = dict(getattr(ctx.room.local_participant, "attributes", {}) or {})
            current_attributes.update(
                {
                    "cozmo.greeting_state": "interrupted",
                    "cozmo.greeting_text": rendered.transcript_text,
                    "cozmo.greeting_interruption_reason": coordinator.interruption_reason or "caller_speech",
                }
            )
            await ctx.room.local_participant.set_attributes(current_attributes)
            raise GreetingPlaybackInterrupted(coordinator.interruption_reason or "caller_speech")

        await source.wait_for_playout()
        current_attributes = dict(getattr(ctx.room.local_participant, "attributes", {}) or {})
        current_attributes.update(
            {
                "cozmo.greeting_state": "published",
                "cozmo.greeting_text": rendered.transcript_text,
            }
        )
        await ctx.room.local_participant.set_attributes(
            current_attributes
        )
        record_greeting_publish(settings.worker_name, agent_config_id)
    finally:
        coordinator.finish_response()
        try:
            await ctx.room.local_participant.unpublish_track(publication.sid)
        finally:
            await source.aclose()


async def _persist_greeting_transcript(
    recorder: TranscriptRecorder | None,
    *,
    greeting_text: str,
    room_name: str,
    agent_config_id: str,
) -> Any | None:
    """Persist the initial greeting as the first agent transcript turn."""

    if recorder is None:
        return None

    try:
        return await asyncio.to_thread(recorder.record_agent_turn, greeting_text)
    except Exception:
        LOGGER.exception(
            "failed to persist greeting transcript",
            extra={
                "room_name": room_name,
                "agent_config_id": agent_config_id,
            },
        )
        return None


def _build_runtime_config(settings: Settings, *, resolved: Any) -> AgentRuntimeConfig:
    """Project the resolved DID-bound config into the effective live-call runtime."""

    runtime = AgentRuntimeConfig.from_agent_config(
        resolved.agent_config,
        max_history_turns=settings.max_history_turns,
        retrieval=settings.retrieval_settings(),
        timeouts=settings.timeout_settings(),
    )
    return runtime.model_copy(
        update={
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model,
            "tts_provider": settings.tts_provider,
            "tts_model": settings.tts_model,
            "tts_voice": settings.tts_voice,
        }
    )


def _message_timestamp(created_at: object) -> datetime | None:
    """Convert LiveKit floating-second timestamps into UTC datetimes."""

    if not isinstance(created_at, (int, float)):
        return None
    return datetime.fromtimestamp(float(created_at), tz=UTC)


def _metric_value_ms(metrics: Mapping[str, object], key: str) -> float | None:
    """Normalize a numeric LiveKit timing metric into milliseconds."""

    value = metrics.get(key)
    if not isinstance(value, (int, float)):
        return None
    return float(value) * 1000.0


def _latency_from_chat_message(message: Any) -> TurnLatencyMetrics:
    """Project LiveKit chat-message timing into the shared latency schema."""

    raw_metrics = getattr(message, "metrics", None)
    metrics = raw_metrics if isinstance(raw_metrics, Mapping) else {}
    endpoint_ms = _metric_value_ms(metrics, "end_of_turn_delay")
    stt_ms = _metric_value_ms(metrics, "transcription_delay")
    llm_ttft_ms = _metric_value_ms(metrics, "llm_node_ttft")
    tts_first_audio_ms = _metric_value_ms(metrics, "tts_node_ttfb")
    pipeline_rtt_ms = calculate_pipeline_rtt_ms(
        stt_ms=stt_ms,
        llm_ttft_ms=llm_ttft_ms,
        tts_first_audio_ms=tts_first_audio_ms,
    )
    perceived_rtt_ms = _metric_value_ms(metrics, "e2e_latency")
    if perceived_rtt_ms is None:
        perceived_rtt_ms = calculate_perceived_rtt_ms(
            endpoint_ms=endpoint_ms,
            stt_ms=stt_ms,
            llm_ttft_ms=llm_ttft_ms,
            tts_first_audio_ms=tts_first_audio_ms,
        )
    return TurnLatencyMetrics(
        endpoint_ms=endpoint_ms,
        stt_ms=stt_ms,
        llm_ttft_ms=llm_ttft_ms,
        tts_first_audio_ms=tts_first_audio_ms,
        pipeline_rtt_ms=pipeline_rtt_ms,
        perceived_rtt_ms=perceived_rtt_ms,
    )


async def _persist_livekit_chat_message(
    recorder: TranscriptRecorder | None,
    *,
    message: Any,
    settings: Settings,
    runtime_config: AgentRuntimeConfig,
) -> None:
    """Persist a user or assistant message emitted by the live AgentSession."""

    if recorder is None:
        return

    role = getattr(message, "role", None)
    if role not in {"user", "assistant"}:
        return

    text = " ".join(str(getattr(message, "text_content", "") or "").split()).strip()
    if not text:
        return

    interrupted = bool(getattr(message, "interrupted", False))
    latency = _latency_from_chat_message(message)
    record_method = recorder.record_agent_turn if role == "assistant" else recorder.record_user_turn

    await asyncio.to_thread(
        record_method,
        text,
        timestamp=_message_timestamp(getattr(message, "created_at", None)),
        interrupted=interrupted,
        latency=latency,
        idempotency_key=f"livekit-message:{getattr(message, 'id', text)}",
    )

    if role == "assistant":
        record_turn_latency_metrics(
            settings.worker_name,
            runtime_config.config_id,
            latency,
        )
        if interrupted:
            record_response_interrupt(settings.worker_name, "caller_speech")
            record_interrupted_agent_turn(settings.worker_name, runtime_config.config_id)


def _build_live_agent_instructions(runtime_config: AgentRuntimeConfig) -> str:
    """Build the instruction string used by the real voice session."""

    return PromptBuilder().build_system_prompt(
        runtime_config=runtime_config,
        knowledge_chunks=(),
    )


def _create_live_agent_session(settings: Settings) -> Any:
    """Create a real AgentSession backed by the configured providers."""

    from livekit.agents import APIConnectOptions, AgentSession
    from livekit.agents.voice.agent_session import SessionConnectOptions

    return AgentSession(
        stt=SttAdapter.from_settings(settings).create_provider(),
        llm=LlmAdapter.from_settings(settings).create_provider(),
        tts=TtsAdapter.from_settings(settings).create_provider(),
        conn_options=SessionConnectOptions(
            stt_conn_options=APIConnectOptions(timeout=settings.timeout_stt_ms / 1000.0),
            llm_conn_options=APIConnectOptions(timeout=settings.timeout_llm_ms / 1000.0),
            tts_conn_options=APIConnectOptions(timeout=settings.timeout_tts_ms / 1000.0),
        ),
    )


def _build_live_agent(runtime_config: AgentRuntimeConfig) -> Any:
    """Create the LiveKit Agent definition for one inbound call."""

    from livekit.agents import Agent

    return Agent(instructions=_build_live_agent_instructions(runtime_config))


def _install_live_session_handlers(
    session: Any,
    *,
    controller: LiveSessionController,
    recorder: TranscriptRecorder | None,
    settings: Settings,
    runtime_config: AgentRuntimeConfig,
) -> None:
    """Attach persistence and shutdown hooks to a live AgentSession."""

    def on_conversation_item_added(event: Any) -> None:
        message = getattr(event, "item", None)
        if message is None:
            return
        controller.schedule(
            _persist_livekit_chat_message(
                recorder,
                message=message,
                settings=settings,
                runtime_config=runtime_config,
            )
        )

    def on_close(event: Any) -> None:
        reason = getattr(event, "reason", None)
        controller.close_reason = getattr(reason, "value", None) or str(reason or "")
        controller.close_error = getattr(event, "error", None)
        controller.close_event.set()

    def on_error(event: Any) -> None:
        LOGGER.warning(
            "live agent session emitted an error",
            extra={
                "source": type(getattr(event, "source", None)).__name__,
                "error": str(getattr(event, "error", None) or ""),
                "agent_config_id": runtime_config.config_id,
            },
        )

    session.on("conversation_item_added", on_conversation_item_added)
    session.on("close", on_close)
    session.on("error", on_error)


async def _run_live_agent_loop(
    ctx: Any,
    *,
    settings: Settings,
    resolved: Any,
    transcript_recorder: TranscriptRecorder | None,
    participant_identity: str | None,
) -> None:
    """Run the provider-backed voice loop for the active room."""

    from livekit.agents import room_io

    runtime_config = _build_runtime_config(settings, resolved=resolved)
    session = _create_live_agent_session(settings)
    controller = LiveSessionController()
    _install_live_session_handlers(
        session,
        controller=controller,
        recorder=transcript_recorder,
        settings=settings,
        runtime_config=runtime_config,
    )

    await session.start(
        _build_live_agent(runtime_config),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            text_input=False,
            participant_identity=participant_identity,
        ),
        record=False,
    )

    greeting_text = build_initial_greeting(runtime_config.agent_name)
    try:
        greeting_handle = session.say(greeting_text, add_to_chat_ctx=True)
        await greeting_handle
        if not greeting_handle.interrupted:
            record_greeting_publish(settings.worker_name, runtime_config.config_id)
    except Exception:
        record_greeting_publish_failure(settings.worker_name, "publish_error")
        LOGGER.exception(
            "failed to publish provider-backed greeting audio",
            extra={
                "room_name": resolved.room_name,
                "agent_config_id": runtime_config.config_id,
            },
        )

    room_disconnected = asyncio.create_task(_wait_for_room_disconnect(ctx.room))
    session_closed = asyncio.create_task(controller.close_event.wait())
    try:
        done, pending = await asyncio.wait(
            {room_disconnected, session_closed},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await controller.drain()
        if session_closed in done and controller.close_reason == "error":
            raise RuntimeError(str(controller.close_error or "live agent session closed with error"))
    finally:
        await session.aclose()


async def _bootstrap_job(
    ctx: Any,
    *,
    settings: Settings,
    store: MongoAgentConfigStore,
    transcript_store: MongoTranscriptStore,
    dead_letter_store: MongoTranscriptDeadLetterStore,
    call_state_store: MongoCallStateStore,
) -> None:
    """Join the dispatched room and resolve the Mongo-backed runtime context once."""

    from livekit import rtc
    from livekit.agents import AutoSubscribe

    setup_started = perf_counter()
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant(kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP)

    try:
        resolved = await asyncio.to_thread(
            resolve_call_context,
            repository=store.repository,
            room_name=ctx.room.name,
            participant_attributes=getattr(participant, "attributes", None),
            participant_identity=getattr(participant, "identity", None),
            participant_kind=getattr(participant, "kind", None),
        )
    except AgentBootstrapError as exc:
        record_job_bootstrap_failure(settings.worker_name, "agent_config_lookup")
        local_participant = getattr(ctx.room, "local_participant", None)
        if local_participant is not None:
            await local_participant.set_attributes(
                {
                    "cozmo.bootstrap_state": "failed",
                    "cozmo.bootstrap_error": str(exc),
                }
            )
        raise

    local_participant = ctx.room.local_participant
    await local_participant.set_attributes(resolved.participant_attributes())
    await local_participant.set_metadata(
        json.dumps(resolved.participant_metadata(), separators=(",", ":"))
    )
    record_call_setup(
        settings.worker_name,
        resolved.agent_config.config_id,
        call_setup_ms=(perf_counter() - setup_started) * 1000,
    )
    transcript_recorder = TranscriptRecorder.from_sink(
        room_name=resolved.room_name,
        sink=transcript_store.repository,
        dead_letter_sink=dead_letter_store.repository,
        max_retries=2,
    )
    quality_monitor = RoomQualityMonitor(
        room=ctx.room,
        worker_name=settings.worker_name,
        agent_config_id=resolved.agent_config.config_id,
        room_name=resolved.room_name,
        poll_interval_ms=settings.room_quality_poll_interval_ms,
        call_state_sink=call_state_store.repository,
    )
    quality_task = asyncio.create_task(quality_monitor.run())
    record_job_bootstrap(settings.worker_name, resolved.agent_config.config_id)
    LOGGER.info(
        "bootstrapped inbound call",
        extra={
            "room_name": resolved.room_name,
            "did": resolved.did,
            "provider_call_id": resolved.provider_call_id,
            "agent_config_id": resolved.agent_config.config_id,
        },
    )
    try:
        await _run_live_agent_loop(
            ctx,
            settings=settings,
            resolved=resolved,
            transcript_recorder=transcript_recorder,
            participant_identity=getattr(participant, "identity", None),
        )
    except Exception:
        LOGGER.exception(
            "live agent loop failed",
            extra={
                "room_name": resolved.room_name,
                "agent_config_id": resolved.agent_config.config_id,
            },
        )
        raise
    finally:
        quality_task.cancel()
        await asyncio.gather(quality_task, return_exceptions=True)


async def _plan_recovery_after_failure(
    ctx: Any,
    *,
    settings: Settings,
    recovery_coordinator: RejoinCoordinator,
    call_state_store: MongoCallStateStore,
) -> None:
    """Mark a room recoverable once and annotate local state for a replacement job."""

    room_name = str(getattr(getattr(ctx, "room", None), "name", "") or "")
    if not room_name_matches_prefix(room_name, settings.call_room_prefix):
        return

    plan = await asyncio.to_thread(recovery_coordinator.plan_replacement, room_name)
    if not plan.should_dispatch_replacement:
        return

    await asyncio.to_thread(call_state_store.repository.mark_recovery_pending, room_name)
    local_participant = getattr(getattr(ctx, "room", None), "local_participant", None)
    if local_participant is not None:
        current_attributes = dict(getattr(local_participant, "attributes", {}) or {})
        current_attributes.update(
            {
                "cozmo.recovery_state": "recoverable",
                "cozmo.recovery_dispatch": "replacement_requested",
                "cozmo.recovery_prompt": plan.recovery_prompt or "",
            }
        )
        await local_participant.set_attributes(current_attributes)
    LOGGER.warning(
        "planned replacement recovery job",
        extra={
            "room_name": room_name,
            "history_turns": len(plan.history_turns),
        },
    )
    record_recovery(settings.worker_name)


async def inbound_agent_request(req: Any) -> None:
    """Accept only rooms that match the configured inbound dispatch prefix."""

    settings = get_settings()
    job = getattr(req, "job", None)
    room = getattr(job, "room", None)
    room_name = str(getattr(room, "name", "") or "")
    if not room_name_matches_prefix(room_name, settings.call_room_prefix):
        await req.reject()
        return

    await req.accept(
        name=settings.livekit_dispatch_agent_name,
        identity=build_agent_identity(settings.worker_name, room_name),
        attributes={
            "cozmo.worker_name": settings.worker_name,
            "cozmo.bootstrap_state": "accepted",
        },
    )


async def inbound_agent_entrypoint(ctx: Any) -> None:
    """Join the room and resolve the per-call runtime context."""

    settings = get_settings()
    store = MongoAgentConfigStore.from_settings(settings)
    transcript_store = MongoTranscriptStore.from_connection(
        client=store.client,
        database_name=settings.mongo_database or "cozmo",
    )
    dead_letter_store = MongoTranscriptDeadLetterStore.from_connection(
        client=store.client,
        database_name=settings.mongo_database or "cozmo",
    )
    recovery_store = MongoRecoveryStore.from_connection(
        client=store.client,
        database_name=settings.mongo_database or "cozmo",
    )
    call_state_store = MongoCallStateStore.from_connection(
        client=store.client,
        database_name=settings.mongo_database or "cozmo",
    )
    record_job_started(
        settings.worker_name,
        max_jobs=settings.max_jobs_per_worker_server,
    )
    try:
        await _bootstrap_job(
            ctx,
            settings=settings,
            store=store,
            transcript_store=transcript_store,
            dead_letter_store=dead_letter_store,
            call_state_store=call_state_store,
        )
    except AgentBootstrapError as exc:
        LOGGER.warning("bootstrap rejected inbound call: %s", exc)
        raise
    except Exception:
        await _plan_recovery_after_failure(
            ctx,
            settings=settings,
            recovery_coordinator=RejoinCoordinator(
                lease_sink=recovery_store.repository,
                transcript_source=transcript_store.repository,
            ),
            call_state_store=call_state_store,
        )
        LOGGER.exception("unexpected worker bootstrap failure")
        raise
    finally:
        record_job_finished(
            settings.worker_name,
            max_jobs=settings.max_jobs_per_worker_server,
        )
        store.close()


def create_worker_server(settings: Settings | None = None) -> Any:
    """Create the LiveKit agent server for inbound telephony jobs."""

    from livekit.agents import AgentServer

    settings = settings or get_settings()
    server = AgentServer(
        ws_url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    server.rtc_session(
        inbound_agent_entrypoint,
        agent_name=settings.livekit_dispatch_agent_name,
        on_request=inbound_agent_request,
    )
    return server


def run_worker() -> None:
    """Start the LiveKit worker runtime."""

    from livekit.agents import cli
    from prometheus_client import start_http_server

    settings = get_settings()
    export_provider_environment(settings)
    if settings.metrics_enabled:
        start_http_server(settings.metrics_port)
        WorkerSystemMonitor(
            worker_name=settings.worker_name,
            poll_interval_ms=settings.system_metrics_poll_interval_ms,
        ).start_in_background()
    record_worker_start(settings.worker_name)
    cli.run_app(create_worker_server(settings))
