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
def test_backend_healthcheck_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    inserted_paths = add_repo_paths()

    try:
        from app import main as main_module

        fake_resources = FakeMongoResources(
            call_sessions=FakeCallSessionRepository([]),
            transcripts=FakeTranscriptRepository([]),
            agent_configs=FakeAgentConfigRepository([]),
        )
        monkeypatch.setattr(main_module, "get_settings", lambda: build_settings())
        monkeypatch.setattr(
            main_module,
            "MongoResources",
            build_mongo_factory(fake_resources),
        )

        app = main_module.create_app()
        with TestClient(app) as client:
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
    finally:
        remove_repo_paths(*inserted_paths)
