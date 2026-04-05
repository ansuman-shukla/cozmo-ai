"""Compatibility wrapper for ingestion helpers."""

from cozmo_knowledge.ingest import (
    build_documents_from_payload,
    faq_items_to_documents,
    ingest_text,
    parse_file_content,
)

__all__ = [
    "build_documents_from_payload",
    "faq_items_to_documents",
    "ingest_text",
    "parse_file_content",
]
