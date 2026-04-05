import sys
from pathlib import Path

import pytest


@pytest.mark.unit
def test_chunk_text_returns_overlapping_chunks() -> None:
    knowledge_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(knowledge_root))

    try:
        from chunker import chunk_text

        chunks = chunk_text("abcdefghij", chunk_size=4, overlap=1)
        assert chunks == ["abcd", "defg", "ghij", "j"]
    finally:
        sys.path.remove(str(knowledge_root))
        sys.modules.pop("chunker", None)


@pytest.mark.unit
def test_chunk_document_returns_stable_chunk_ids() -> None:
    knowledge_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(knowledge_root))

    try:
        from cozmo_knowledge.chunker import chunk_document
        from cozmo_knowledge.models import KnowledgeDocument

        chunks = chunk_document(
            KnowledgeDocument(
                document_id="doc-1",
                collection_name="main-faq",
                text="abcdefghij",
            ),
            chunk_size=4,
            overlap=1,
        )

        assert [chunk.chunk_id for chunk in chunks] == [
            "doc-1:chunk:0",
            "doc-1:chunk:1",
            "doc-1:chunk:2",
            "doc-1:chunk:3",
        ]
    finally:
        sys.path.remove(str(knowledge_root))
        sys.modules.pop("cozmo_knowledge.chunker", None)
        sys.modules.pop("cozmo_knowledge.models", None)
