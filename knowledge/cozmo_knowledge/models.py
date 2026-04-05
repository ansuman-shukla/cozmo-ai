"""Typed document and retrieval shapes for the knowledge subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

ScalarMetadata = str | int | float | bool
MetadataMap = dict[str, ScalarMetadata]


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    """One normalized source document ready for chunking."""

    document_id: str
    collection_name: str
    text: str
    title: str | None = None
    source_type: Literal["text", "faq", "file"] = "text"
    metadata: MetadataMap = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class KnowledgeFaqItem:
    """A structured FAQ entry accepted by ingestion."""

    question: str
    answer: str
    item_id: str | None = None
    metadata: MetadataMap = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class KnowledgeFileInput:
    """A file-shaped ingestion payload."""

    document_id: str
    file_name: str
    content: str
    metadata: MetadataMap = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    """One chunk written to the vector store."""

    chunk_id: str
    document_id: str
    collection_name: str
    text: str
    start_char: int
    end_char: int
    metadata: MetadataMap = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievedKnowledgeChunk:
    """A normalized retrieval result returned to the backend or agent."""

    chunk_id: str
    document_id: str
    text: str
    score: float
    metadata: MetadataMap = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IngestJobRecord:
    """Observable status for one ingestion request."""

    job_id: str
    collection_name: str
    status: Literal["queued", "running", "completed", "failed"]
    document_count: int = 0
    chunk_count: int = 0
    error: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
