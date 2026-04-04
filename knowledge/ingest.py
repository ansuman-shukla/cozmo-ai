"""Knowledge ingestion entrypoints."""

from chunker import chunk_text


def ingest_text(document_id: str, text: str, chunk_size: int = 400, overlap: int = 40) -> dict:
    """Chunk text and return an ingestion payload skeleton."""

    return {
        "document_id": document_id,
        "chunks": chunk_text(text=text, chunk_size=chunk_size, overlap=overlap),
    }

