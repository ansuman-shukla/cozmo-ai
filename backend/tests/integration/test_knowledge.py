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
def test_knowledge_routes_ingest_query_and_report_job_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inserted_paths = add_repo_paths()

    try:
        from app import main as main_module

        fake_resources = FakeMongoResources(
            call_sessions=FakeCallSessionRepository([]),
            transcripts=FakeTranscriptRepository([]),
            agent_configs=FakeAgentConfigRepository([]),
        )
        monkeypatch.setattr(
            main_module,
            "get_settings",
            lambda: build_settings(chroma_uri="memory://", embedding_model="local-hash-v1"),
        )
        monkeypatch.setattr(main_module, "MongoResources", build_mongo_factory(fake_resources))

        app = main_module.create_app()

        ingest_payload = {
            "collection_name": "main-faq",
            "faq_items": [
                {
                    "question": "What does the starter plan cost?",
                    "answer": "The starter plan costs twenty nine dollars per month.",
                },
                {
                    "question": "Do you offer phone support?",
                    "answer": "Phone support is available on the growth plan and above.",
                },
            ],
        }

        with TestClient(app) as client:
            created = client.post("/knowledge/ingest", json=ingest_payload)
            assert created.status_code == 202
            assert created.json()["status"] == "completed"
            assert created.json()["document_count"] == 2
            assert created.json()["chunk_count"] >= 2

            job = client.get(f"/knowledge/jobs/{created.json()['job_id']}")
            assert job.status_code == 200
            assert job.json()["status"] == "completed"

            query = client.post(
                "/knowledge/query",
                json={
                    "collection_name": "main-faq",
                    "query_text": "starter plan cost",
                },
            )

        assert query.status_code == 200
        assert query.json()["matches"]
        assert "starter plan" in query.json()["matches"][0]["text"].lower()
    finally:
        remove_repo_paths(*inserted_paths)


@pytest.mark.integration
def test_knowledge_routes_accept_json_file_faq_ingestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inserted_paths = add_repo_paths()

    try:
        from app import main as main_module

        fake_resources = FakeMongoResources(
            call_sessions=FakeCallSessionRepository([]),
            transcripts=FakeTranscriptRepository([]),
            agent_configs=FakeAgentConfigRepository([]),
        )
        monkeypatch.setattr(
            main_module,
            "get_settings",
            lambda: build_settings(chroma_uri="memory://", embedding_model="local-hash-v1"),
        )
        monkeypatch.setattr(main_module, "MongoResources", build_mongo_factory(fake_resources))

        app = main_module.create_app()

        with TestClient(app) as client:
            created = client.post(
                "/knowledge/ingest",
                json={
                    "collection_name": "support-faq",
                    "files": [
                        {
                            "document_id": "support-json",
                            "file_name": "support.json",
                            "content": '[{"question":"How do I reset my password?","answer":"Use the reset password link on the sign in page."}]',
                        }
                    ],
                },
            )
            query = client.post(
                "/knowledge/query",
                json={
                    "collection_name": "support-faq",
                    "query_text": "reset password",
                },
            )

        assert created.status_code == 202
        assert created.json()["document_count"] == 1
        assert query.status_code == 200
        assert query.json()["matches"][0]["document_id"].startswith("support-json")
    finally:
        remove_repo_paths(*inserted_paths)
