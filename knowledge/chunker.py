"""Chunking helpers for knowledge ingestion."""


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 40) -> list[str]:
    """Split text into overlapping chunks."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be between 0 and chunk_size - 1")
    if not text:
        return []

    step = chunk_size - overlap
    return [text[index : index + chunk_size] for index in range(0, len(text), step)]

