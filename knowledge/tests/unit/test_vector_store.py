import sys
from pathlib import Path

import pytest


@pytest.mark.unit
def test_in_memory_vector_store_returns_top_k_filtered_matches() -> None:
    knowledge_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(knowledge_root))

    try:
        from cozmo_knowledge.embeddings import EmbeddingAdapter
        from cozmo_knowledge.models import KnowledgeChunk
        from cozmo_knowledge.vector_store import InMemoryVectorStore

        adapter = EmbeddingAdapter(model_name="local-hash-v1", dimensions=64)
        store = InMemoryVectorStore()
        chunks = [
            KnowledgeChunk(
                chunk_id="c1",
                document_id="doc-1",
                collection_name="main-faq",
                text="starter plan pricing is twenty nine dollars",
                start_char=0,
                end_char=40,
            ),
            KnowledgeChunk(
                chunk_id="c2",
                document_id="doc-2",
                collection_name="main-faq",
                text="password reset instructions are available online",
                start_char=0,
                end_char=45,
            ),
        ]
        store.upsert("main-faq", chunks=chunks, embeddings=adapter.embed_many([chunk.text for chunk in chunks]))

        results = store.query(
            "main-faq",
            query_embedding=adapter.embed("starter plan price"),
            top_k=1,
            min_score=0.1,
        )

        assert len(results) == 1
        assert results[0].chunk_id == "c1"
    finally:
        sys.path.remove(str(knowledge_root))
        sys.modules.pop("cozmo_knowledge.embeddings", None)
        sys.modules.pop("cozmo_knowledge.models", None)
        sys.modules.pop("cozmo_knowledge.vector_store", None)


@pytest.mark.unit
def test_chroma_vector_store_wraps_version_mismatch_error() -> None:
    knowledge_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(knowledge_root))

    try:
        from cozmo_knowledge.vector_store import ChromaVectorStore, VectorStoreError

        class FakeClient:
            def get_or_create_collection(self, *, name: str, metadata: dict[str, str]) -> None:
                raise Exception("{\"error\":\"KeyError('_type')\"} (trace ID: 0)")

        store = ChromaVectorStore(client=FakeClient())

        with pytest.raises(VectorStoreError, match="Python client and server are on incompatible versions"):
            store.count("main-faq")
    finally:
        sys.path.remove(str(knowledge_root))
        sys.modules.pop("cozmo_knowledge.vector_store", None)


@pytest.mark.unit
def test_in_memory_vector_store_returns_no_matches_below_threshold() -> None:
    knowledge_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(knowledge_root))

    try:
        from cozmo_knowledge.embeddings import EmbeddingAdapter
        from cozmo_knowledge.models import KnowledgeChunk
        from cozmo_knowledge.vector_store import InMemoryVectorStore

        adapter = EmbeddingAdapter(model_name="local-hash-v1", dimensions=64)
        store = InMemoryVectorStore()
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
            query_embedding=adapter.embed("completely unrelated request"),
            top_k=3,
            min_score=0.95,
        )

        assert results == []
    finally:
        sys.path.remove(str(knowledge_root))
        sys.modules.pop("cozmo_knowledge.embeddings", None)
        sys.modules.pop("cozmo_knowledge.models", None)
        sys.modules.pop("cozmo_knowledge.vector_store", None)
