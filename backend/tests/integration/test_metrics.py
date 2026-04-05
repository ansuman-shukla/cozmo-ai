from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from .support import (
    FakeAgentConfigRepository,
    FakeCallSessionRepository,
    FakeMongoResources,
    FakeTranscriptRepository,
    add_repo_paths,
    build_mongo_factory,
    build_settings,
    remove_repo_paths,
)


@pytest.mark.integration
def test_backend_metrics_scrape_exposes_required_session_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inserted_paths = add_repo_paths()

    try:
        from app import main as main_module
        from cozmo_contracts.models import (
            CallDisposition,
            CallSessionRecord,
            CallSessionStatus,
            VoiceQualityMetrics,
        )

        now = datetime.now(UTC)
        fake_resources = FakeMongoResources(
            call_sessions=FakeCallSessionRepository(
                [
                    CallSessionRecord(
                        provider="twilio",
                        provider_call_id="CA-active",
                        room_name="call-active",
                        did="+16625640501",
                        ani="+919262561716",
                        agent_config_id="main-inbound",
                        status=CallSessionStatus.ACTIVE,
                        created_at=now,
                    ),
                    CallSessionRecord(
                        provider="twilio",
                        provider_call_id="CA-failed",
                        room_name="call-failed",
                        did="+16625640501",
                        ani="+919262561716",
                        agent_config_id="fallback-unmapped-did",
                        status=CallSessionStatus.FAILED,
                        created_at=now,
                        disposition=CallDisposition.SETUP_FAILED,
                    ),
                    CallSessionRecord(
                        provider="twilio",
                        provider_call_id="CA-completed",
                        room_name="call-completed",
                        did="+16625640501",
                        ani="+919262561716",
                        agent_config_id="main-inbound",
                        status=CallSessionStatus.COMPLETED,
                        created_at=now,
                        voice_quality=VoiceQualityMetrics(
                            avg_jitter_ms=14.5,
                            packet_loss_pct=0.7,
                            mos_estimate=4.11,
                        ),
                    ),
                ]
            ),
            transcripts=FakeTranscriptRepository([]),
            agent_configs=FakeAgentConfigRepository([]),
        )
        monkeypatch.setattr(main_module, "get_settings", lambda: build_settings())
        monkeypatch.setattr(main_module, "MongoResources", build_mongo_factory(fake_resources))

        app = main_module.create_app()
        with TestClient(app) as client:
            response = client.get("/metrics")

        assert response.status_code == 200
        assert "cozmo_backend_healthcheck_total" in response.text
        assert "cozmo_active_calls 1.0" in response.text
        assert "cozmo_failed_call_setups_total 1.0" in response.text
        assert "cozmo_failed_call_setup_rate_pct 33.33333333333333" in response.text
        assert 'cozmo_persisted_room_jitter_ms{agent_config_id="main-inbound"} 14.5' in response.text
        assert 'cozmo_persisted_room_packet_loss_pct{agent_config_id="main-inbound"} 0.7' in response.text
        assert 'cozmo_persisted_room_mos_estimate{agent_config_id="main-inbound"} 4.11' in response.text
    finally:
        remove_repo_paths(*inserted_paths)
