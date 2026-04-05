"""Chunking helpers for knowledge ingestion."""

from __future__ import annotations

from .models import KnowledgeChunk, KnowledgeDocument


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 40) -> list[str]:
    """Split text into overlapping chunks."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be between 0 and chunk_size - 1")
    if not text:
        return []

    step = chunk_size - overlap
    chunks: list[str] = []
    for index in range(0, len(text), step):
        chunk = text[index : index + chunk_size]
        if chunk:
            chunks.append(chunk)
    return chunks


def chunk_document(
    document: KnowledgeDocument,
    *,
    chunk_size: int = 400,
    overlap: int = 40,
) -> list[KnowledgeChunk]:
    """Split one normalized document into chunk records with stable ids."""

    raw_chunks = chunk_text(document.text, chunk_size=chunk_size, overlap=overlap)
    chunks: list[KnowledgeChunk] = []
    step = chunk_size - overlap
    for index, text in enumerate(raw_chunks):
        start_char = index * step
        end_char = min(start_char + len(text), len(document.text))
        metadata = {
            **document.metadata,
            "source_type": document.source_type,
        }
        if document.title:
            metadata["title"] = document.title
        chunks.append(
            KnowledgeChunk(
                chunk_id=f"{document.document_id}:chunk:{index}",
                document_id=document.document_id,
                collection_name=document.collection_name,
                text=text,
                start_char=start_char,
                end_char=end_char,
                metadata=metadata,
            )
        )
    return chunks


def chunk_documents(
    documents: list[KnowledgeDocument],
    *,
    chunk_size: int = 400,
    overlap: int = 40,
) -> list[KnowledgeChunk]:
    """Split multiple documents into one flat chunk list."""

    chunks: list[KnowledgeChunk] = []
    for document in documents:
        chunks.extend(chunk_document(document, chunk_size=chunk_size, overlap=overlap))
    return chunks
