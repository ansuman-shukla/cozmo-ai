"""Reusable knowledge ingestion and retrieval helpers."""

from .chunker import chunk_document, chunk_documents, chunk_text
from .embeddings import EmbeddingAdapter, EmbeddingAdapterError
from .ingest import (
    build_documents_from_payload,
    faq_items_to_documents,
    ingest_text,
    parse_file_content,
)
from .models import (
    IngestJobRecord,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeFaqItem,
    KnowledgeFileInput,
    RetrievedKnowledgeChunk,
)
from .vector_store import ChromaVectorStore, InMemoryVectorStore, VectorStoreError

__all__ = [
    "ChromaVectorStore",
    "EmbeddingAdapter",
    "EmbeddingAdapterError",
    "InMemoryVectorStore",
    "IngestJobRecord",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeFaqItem",
    "KnowledgeFileInput",
    "RetrievedKnowledgeChunk",
    "VectorStoreError",
    "build_documents_from_payload",
    "chunk_document",
    "chunk_documents",
    "chunk_text",
    "faq_items_to_documents",
    "ingest_text",
    "parse_file_content",
]
