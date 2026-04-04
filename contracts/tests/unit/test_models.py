from datetime import UTC, datetime
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError


CONTRACTS_ROOT = Path(__file__).resolve().parents[2]
if str(CONTRACTS_ROOT) not in sys.path:
    sys.path.insert(0, str(CONTRACTS_ROOT))

from cozmo_contracts.models import (  # noqa: E402
    AgentConfigRecord,
    CallMetricsSummary,
    CallSessionRecord,
    CallSessionStatus,
    KnowledgeChunkReference,
    TranscriptTurn,
    TurnLatencyMetrics,
    VoiceQualityMetrics,
)


@pytest.mark.unit
def test_call_session_accepts_valid_payload() -> None:
    record = CallSessionRecord(
        provider="twilio",
        provider_call_id="CA123456789",
        room_name="call-12345",
        did="+15551234567",
        ani="+15557654321",
        agent_config_id="sales-main",
        status=CallSessionStatus.ACTIVE,
        created_at=datetime.now(UTC),
        connected_at=datetime.now(UTC),
        metrics_summary=CallMetricsSummary(
            avg_perceived_rtt_ms=540.0,
            p95_perceived_rtt_ms=870.0,
            avg_pipeline_rtt_ms=410.0,
            avg_stt_ms=125.0,
            avg_llm_ttft_ms=210.0,
            avg_tts_first_audio_ms=110.0,
            call_setup_ms=820.0,
        ),
        voice_quality=VoiceQualityMetrics(
            avg_jitter_ms=12.0,
            packet_loss_pct=0.4,
            mos_estimate=4.1,
        ),
    )

    assert record.status is CallSessionStatus.ACTIVE
    assert record.metrics_summary.avg_perceived_rtt_ms == 540.0
    assert record.voice_quality.mos_estimate == 4.1


@pytest.mark.unit
def test_call_session_accepts_livekit_phone_room_name() -> None:
    record = CallSessionRecord(
        provider="twilio",
        provider_call_id="CA123456789",
        room_name="call-+16625640501-a1b2c3",
        did="+16625640501",
        ani="+15557654321",
        agent_config_id="sales-main",
        status=CallSessionStatus.CREATED,
        created_at=datetime.now(UTC),
    )

    assert record.room_name == "call-+16625640501-a1b2c3"


@pytest.mark.unit
def test_call_session_rejects_invalid_did() -> None:
    with pytest.raises(ValidationError):
        CallSessionRecord(
            provider="twilio",
            room_name="call-12345",
            did="15551234567",
            agent_config_id="sales-main",
            status=CallSessionStatus.CREATED,
            created_at=datetime.now(UTC),
        )


@pytest.mark.unit
def test_transcript_rejects_invalid_room_name() -> None:
    with pytest.raises(ValidationError):
        TranscriptTurn(
            room_name="call invalid",
            turn_index=0,
            speaker="user",
            text="hello",
            timestamp=datetime.now(UTC),
        )


@pytest.mark.unit
def test_agent_config_rejects_invalid_transfer_target() -> None:
    with pytest.raises(ValidationError):
        AgentConfigRecord(
            config_id="sales-main",
            did="+15551234567",
            agent_name="Sales Agent",
            persona_prompt="Help the caller with plan selection.",
            kb_collection="sales-faq",
            llm_provider="openai",
            llm_model="gpt-realtime-mini",
            tts_provider="deepgram",
            tts_model="aura-2-thalia-en",
            tts_voice="thalia",
            escalation_triggers=["human", "manager"],
            transfer_target="human-desk",
        )


@pytest.mark.unit
def test_transcript_accepts_latency_and_kb_references() -> None:
    turn = TranscriptTurn(
        room_name="call-98765",
        turn_index=1,
        speaker="agent",
        text="Here is the answer.",
        timestamp=datetime.now(UTC),
        interrupted=False,
        latency=TurnLatencyMetrics(
            endpoint_ms=220.0,
            stt_ms=115.0,
            llm_ttft_ms=180.0,
            tts_first_audio_ms=95.0,
            pipeline_rtt_ms=390.0,
            perceived_rtt_ms=575.0,
        ),
        kb_chunks_used=[
            KnowledgeChunkReference(chunk_id="faq-1#0", score=0.81),
        ],
    )

    assert turn.latency.llm_ttft_ms == 180.0
    assert turn.kb_chunks_used[0].chunk_id == "faq-1#0"
