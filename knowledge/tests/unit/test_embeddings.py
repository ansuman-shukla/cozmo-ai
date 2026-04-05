import sys
from pathlib import Path

import pytest


@pytest.mark.unit
def test_local_embedding_adapter_is_deterministic() -> None:
    knowledge_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(knowledge_root))

    try:
        from cozmo_knowledge.embeddings import EmbeddingAdapter

        adapter = EmbeddingAdapter(model_name="local-hash-v1", dimensions=32)
        first = adapter.embed("starter plan pricing")
        second = adapter.embed("starter plan pricing")

        assert first == second
        assert len(first) == 32
    finally:
        sys.path.remove(str(knowledge_root))
        sys.modules.pop("cozmo_knowledge.embeddings", None)
