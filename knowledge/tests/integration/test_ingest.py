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

