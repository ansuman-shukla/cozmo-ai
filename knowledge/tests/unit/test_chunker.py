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

