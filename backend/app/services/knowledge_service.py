"""Knowledge retrieval helpers."""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.ingest_jobs import IngestJobService

KNOWLEDGE_ROOT = Path(__file__).resolve().parents[3] / "knowledge"
if str(KNOWLEDGE_ROOT) not in sys.path:
    sys.path.insert(0, str(KNOWLEDGE_ROOT))

from cozmo_knowledge.embeddings import EmbeddingAdapter, EmbeddingAdapterError
from cozmo_knowledge.ingest import build_documents_from_payload
from cozmo_knowledge.models import (
    IngestJobRecord,
    KnowledgeDocument,
    KnowledgeFaqItem,
    KnowledgeFileInput,
    RetrievedKnowledgeChunk,
)
from cozmo_knowledge.vector_store import ChromaVectorStore, InMemoryVectorStore, VectorStoreError


class KnowledgeServiceError(RuntimeError):
    """Raised when ingestion or retrieval cannot be completed."""


class KnowledgeDocumentInput(BaseModel):
    """Plain-text document accepted by the control plane."""

    document_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    title: str | None = None
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class KnowledgeFaqItemInput(BaseModel):
    """FAQ-shaped content accepted by the control plane."""

    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    item_id: str | None = None
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class KnowledgeFileInputModel(BaseModel):
    """File-like content accepted by the control plane."""

    document_id: str = Field(min_length=1)
    file_name: str = Field(min_length=1)
    content: str = Field(min_length=1)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class KnowledgeIngestRequest(BaseModel):
    """Request shape for `/knowledge/ingest`."""

    collection_name: str = Field(min_length=1)
    documents: list[KnowledgeDocumentInput] = Field(default_factory=list)
    faq_items: list[KnowledgeFaqItemInput] = Field(default_factory=list)
    files: list[KnowledgeFileInputModel] = Field(default_factory=list)
    chunk_size: int = Field(default=400, ge=1, le=4000)
    overlap: int = Field(default=40, ge=0, le=3999)


class KnowledgeQueryRequest(BaseModel):
    """Request shape for `/knowledge/query`."""

    collection_name: str = Field(min_length=1)
    query_text: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)
    min_score: float | None = Field(default=None, ge=0.0, le=1.0)


@dataclass(slots=True)
class KnowledgeService:
    """Ingest and query KB content against a vector store."""

    endpoint: str
    vector_store: Any
    embedding_adapter: EmbeddingAdapter
    ingest_jobs: IngestJobService
    default_top_k: int = 3
    default_min_score: float = 0.35

    @classmethod
    def from_settings(cls, settings: Any) -> "KnowledgeService":
        """Build the service from shared backend settings."""

        chroma_uri = str(getattr(settings, "chroma_uri", "memory://") or "memory://").strip()
        if chroma_uri == "memory://":
            vector_store: Any = InMemoryVectorStore()
        else:
            vector_store = ChromaVectorStore.from_uri(chroma_uri)
        return cls(
            endpoint=chroma_uri,
            vector_store=vector_store,
            embedding_adapter=EmbeddingAdapter(
                model_name=str(getattr(settings, "embedding_model", "local-hash-v1")),
                openai_api_key=getattr(settings, "openai_api_key", None),
            ),
            ingest_jobs=IngestJobService(),
            default_top_k=int(getattr(settings, "kb_top_k", 3)),
            default_min_score=float(getattr(settings, "kb_min_score", 0.35)),
        )

    def ping(self) -> dict[str, str]:
        """Return a lightweight health response for the current vector backend."""

        backend_name = "memory"
        if isinstance(self.vector_store, ChromaVectorStore):
            backend_name = "chroma"
        return {"endpoint": self.endpoint, "status": "ready", "backend": backend_name}

    def _normalize_documents(self, request: KnowledgeIngestRequest) -> list[KnowledgeDocument]:
        documents = [
            KnowledgeDocument(
                document_id=item.document_id,
                collection_name=request.collection_name,
                text=item.text.strip(),
                title=item.title,
                source_type="text",
                metadata=item.metadata,
            )
            for item in request.documents
        ]
        faq_items = [
            KnowledgeFaqItem(
                question=item.question,
                answer=item.answer,
                item_id=item.item_id,
                metadata=item.metadata,
            )
            for item in request.faq_items
        ]
        files = [
            KnowledgeFileInput(
                document_id=item.document_id,
                file_name=item.file_name,
                content=item.content,
                metadata=item.metadata,
            )
            for item in request.files
        ]
        return build_documents_from_payload(
            collection_name=request.collection_name,
            documents=documents,
            faq_items=faq_items,
            files=files,
        )

    def ingest(self, request: KnowledgeIngestRequest) -> IngestJobRecord:
        """Synchronously ingest content and record a completed job."""

        if not any((request.documents, request.faq_items, request.files)):
            raise KnowledgeServiceError("At least one document, FAQ item, or file is required.")

        job = self.ingest_jobs.create_job(collection_name=request.collection_name)
        self.ingest_jobs.mark_running(job.job_id)
        try:
            documents = self._normalize_documents(request)
            if not documents:
                raise KnowledgeServiceError("The ingestion payload did not produce any documents.")

            from cozmo_knowledge.chunker import chunk_documents

            chunks = chunk_documents(
                documents,
                chunk_size=request.chunk_size,
                overlap=request.overlap,
            )
            embeddings = self.embedding_adapter.embed_many([chunk.text for chunk in chunks])
            self.vector_store.upsert(
                request.collection_name,
                chunks=chunks,
                embeddings=embeddings,
            )
            return self.ingest_jobs.mark_completed(
                job.job_id,
                document_count=len(documents),
                chunk_count=len(chunks),
            )
        except (EmbeddingAdapterError, VectorStoreError, ValueError, OSError) as exc:
            self.ingest_jobs.mark_failed(job.job_id, error=str(exc))
            raise KnowledgeServiceError(str(exc)) from exc

    def get_job(self, job_id: str) -> IngestJobRecord | None:
        """Return one ingest job."""

        return self.ingest_jobs.get_job(job_id)

    def query(
        self,
        *,
        collection_name: str,
        query_text: str,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> list[RetrievedKnowledgeChunk]:
        """Run a similarity query against one collection."""

        try:
            query_embedding = self.embedding_adapter.embed(query_text)
            return self.vector_store.query(
                collection_name,
                query_embedding=query_embedding,
                top_k=top_k or self.default_top_k,
                min_score=min_score if min_score is not None else self.default_min_score,
            )
        except (EmbeddingAdapterError, VectorStoreError, ValueError, OSError) as exc:
            raise KnowledgeServiceError(str(exc)) from exc


def job_to_payload(job: IngestJobRecord) -> dict[str, Any]:
    """Serialize an ingest job for API responses."""

    return asdict(job)


def matches_to_payload(matches: list[RetrievedKnowledgeChunk]) -> list[dict[str, Any]]:
    """Serialize retrieval matches for API responses."""

    return [asdict(match) for match in matches]
