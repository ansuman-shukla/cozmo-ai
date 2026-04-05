import sys
from pathlib import Path

import pytest


@pytest.mark.integration
def test_ingest_text_creates_chunk_payload() -> None:
    knowledge_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(knowledge_root))

    try:
        from ingest import ingest_text

        payload = ingest_text("doc-1", "abcdefghij", chunk_size=4, overlap=1)
        assert payload["document_id"] == "doc-1"
        assert payload["chunks"][0] == "abcd"
    finally:
        sys.path.remove(str(knowledge_root))
        sys.modules.pop("ingest", None)
        sys.modules.pop("chunker", None)


@pytest.mark.integration
def test_build_documents_from_payload_supports_faq_and_json_file_inputs() -> None:
    knowledge_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(knowledge_root))

    try:
        from cozmo_knowledge.ingest import build_documents_from_payload
        from cozmo_knowledge.models import KnowledgeFaqItem, KnowledgeFileInput

        documents = build_documents_from_payload(
            collection_name="support-faq",
            faq_items=[
                KnowledgeFaqItem(
                    question="How do I reset my password?",
                    answer="Use the reset password link on the sign in page.",
                )
            ],
            files=[
                KnowledgeFileInput(
                    document_id="pricing-json",
                    file_name="pricing.json",
                    content='[{"question":"What does the starter plan cost?","answer":"It costs $29 per month."}]',
                )
            ],
        )

        assert len(documents) == 2
        assert documents[0].source_type == "faq"
        assert documents[1].source_type == "faq"
    finally:
        sys.path.remove(str(knowledge_root))
        sys.modules.pop("cozmo_knowledge.ingest", None)
        sys.modules.pop("cozmo_knowledge.models", None)
