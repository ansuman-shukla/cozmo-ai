"""Per-call worker orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

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
    record_greeting_publish,
    record_greeting_publish_failure,
    record_job_bootstrap,
    record_job_bootstrap_failure,
    record_worker_start,
)
from app.pipeline.tts import TtsAdapter, build_initial_greeting

LOGGER = logging.getLogger(__name__)


async def _wait_for_room_disconnect(room: Any) -> None:
    """Block until the LiveKit room disconnects."""

    disconnected = asyncio.Event()
    room.on("disconnected", lambda *_args, **_kwargs: disconnected.set())
    await disconnected.wait()


async def _publish_greeting_audio(ctx: Any, *, settings: Settings, agent_name: str, agent_config_id: str) -> None:
    """Publish a short greeting-audio placeholder after bootstrap completes."""

    from livekit import rtc

    renderer = TtsAdapter()
    rendered = renderer.synthesize(build_initial_greeting(agent_name))
    source = rtc.AudioSource(rendered.sample_rate, rendered.num_channels, queue_size_ms=2000)
    track = rtc.LocalAudioTrack.create_audio_track("cozmo-greeting", source)
    publication = await ctx.room.local_participant.publish_track(track)

    try:
        for frame_payload in rendered.iter_pcm_frames():
            frame = rtc.AudioFrame(
                data=frame_payload,
                sample_rate=rendered.sample_rate,
                num_channels=rendered.num_channels,
                samples_per_channel=rendered.samples_per_frame,
            )
            await source.capture_frame(frame)
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
        try:
            await ctx.room.local_participant.unpublish_track(publication.sid)
        finally:
            await source.aclose()


async def _bootstrap_job(ctx: Any, *, settings: Settings, store: MongoAgentConfigStore) -> None:
    """Join the dispatched room and resolve the Mongo-backed runtime context once."""

    from livekit import rtc
    from livekit.agents import AutoSubscribe

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
        await _publish_greeting_audio(
            ctx,
            settings=settings,
            agent_name=resolved.agent_config.agent_name,
            agent_config_id=resolved.agent_config.config_id,
        )
    except Exception:
        record_greeting_publish_failure(settings.worker_name, "publish_error")
        LOGGER.exception(
            "failed to publish greeting audio",
            extra={
                "room_name": resolved.room_name,
                "agent_config_id": resolved.agent_config.config_id,
            },
        )
    await _wait_for_room_disconnect(ctx.room)


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
    try:
        await _bootstrap_job(ctx, settings=settings, store=store)
    except AgentBootstrapError as exc:
        LOGGER.warning("bootstrap rejected inbound call: %s", exc)
        raise
    except Exception:
        LOGGER.exception("unexpected worker bootstrap failure")
        raise
    finally:
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

    settings = get_settings()
    export_provider_environment(settings)
    record_worker_start(settings.worker_name)
    cli.run_app(create_worker_server(settings))
