import sys
from pathlib import Path

import pytest


@pytest.mark.integration
def test_chroma_vector_store_persists_and_queries_when_client_is_available() -> None:
    pytest.importorskip("chromadb")

    knowledge_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(knowledge_root))

    try:
        from cozmo_knowledge.embeddings import EmbeddingAdapter
        from cozmo_knowledge.models import KnowledgeChunk
        from cozmo_knowledge.vector_store import ChromaVectorStore

        adapter = EmbeddingAdapter(model_name="local-hash-v1", dimensions=64)
        store = ChromaVectorStore.from_uri("memory://")
        chunks = [
            KnowledgeChunk(
                chunk_id="c1",
                document_id="doc-1",
                collection_name="main-faq",
                text="starter plan pricing is twenty nine dollars",
                start_char=0,
                end_char=40,
            )
        ]
        store.upsert("main-faq", chunks=chunks, embeddings=adapter.embed_many([chunk.text for chunk in chunks]))

        results = store.query(
            "main-faq",
            query_embedding=adapter.embed("starter pricing"),
            top_k=1,
            min_score=0.1,
        )

        assert results
        assert results[0].chunk_id == "c1"
    finally:
        sys.path.remove(str(knowledge_root))
        sys.modules.pop("cozmo_knowledge.embeddings", None)
        sys.modules.pop("cozmo_knowledge.models", None)
        sys.modules.pop("cozmo_knowledge.vector_store", None)
