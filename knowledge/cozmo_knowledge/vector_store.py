"""Vector-store adapters for knowledge retrieval."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from math import sqrt
from typing import Any
from urllib.parse import urlsplit

from .models import KnowledgeChunk, RetrievedKnowledgeChunk


class VectorStoreError(RuntimeError):
    """Raised when vector-store reads or writes fail."""


def _raise_wrapped_chroma_error(exc: Exception) -> None:
    message = str(exc)
    if "KeyError('_type')" in message:
        raise VectorStoreError(
            "Chroma collection creation failed because the Python client and server are on incompatible "
            "versions. This repo targets Chroma 0.5.23 for both. Run `uv sync --all-packages --dev`, "
            "restart the backend, and retry the ingest request."
        ) from exc
    raise VectorStoreError(f"Chroma request failed: {message}") from exc


def _cosine_similarity(lhs: list[float], rhs: list[float]) -> float:
    if not lhs or not rhs or len(lhs) != len(rhs):
        return 0.0
    numerator = sum(left * right for left, right in zip(lhs, rhs, strict=True))
    lhs_norm = sqrt(sum(value * value for value in lhs))
    rhs_norm = sqrt(sum(value * value for value in rhs))
    if lhs_norm <= 0 or rhs_norm <= 0:
        return 0.0
    return numerator / (lhs_norm * rhs_norm)


@dataclass(slots=True)
class InMemoryVectorStore:
    """Simple in-memory vector store used by tests and local fallback mode."""

    collections: dict[str, dict[str, tuple[KnowledgeChunk, list[float]]]]

    def __init__(self) -> None:
        self.collections = {}

    def upsert(self, collection_name: str, *, chunks: list[KnowledgeChunk], embeddings: list[list[float]]) -> int:
        if len(chunks) != len(embeddings):
            raise VectorStoreError("Chunk and embedding counts do not match.")
        collection = self.collections.setdefault(collection_name, {})
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            collection[chunk.chunk_id] = (chunk, [float(value) for value in embedding])
        return len(chunks)

    def query(
        self,
        collection_name: str,
        *,
        query_embedding: list[float],
        top_k: int,
        min_score: float,
    ) -> list[RetrievedKnowledgeChunk]:
        collection = self.collections.get(collection_name, {})
        matches: list[RetrievedKnowledgeChunk] = []
        for chunk, embedding in collection.values():
            score = _cosine_similarity(query_embedding, embedding)
            if score < min_score:
                continue
            matches.append(
                RetrievedKnowledgeChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    text=chunk.text,
                    score=round(score, 6),
                    metadata=chunk.metadata,
                )
            )
        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[:top_k]

    def count(self, collection_name: str) -> int:
        return len(self.collections.get(collection_name, {}))


@dataclass(slots=True)
class ChromaVectorStore:
    """Thin Chroma client wrapper for collection upserts and similarity search."""

    client: Any

    @classmethod
    def from_uri(cls, chroma_uri: str) -> "ChromaVectorStore":
        """Create a Chroma-backed store from a connection URI."""

        try:
            chromadb = importlib.import_module("chromadb")
        except ImportError as exc:
            raise VectorStoreError(
                "Chroma client is not installed; run `uv sync --all-packages --dev`."
            ) from exc

        if chroma_uri == "memory://":
            return cls(client=chromadb.Client())
        if chroma_uri.startswith("file://"):
            path = urlsplit(chroma_uri).path or "./.chromadb"
            return cls(client=chromadb.PersistentClient(path=path))

        parsed = urlsplit(chroma_uri)
        host = parsed.hostname or "localhost"
        port = parsed.port or 8000
        ssl = parsed.scheme == "https"
        return cls(client=chromadb.HttpClient(host=host, port=port, ssl=ssl))

    def _collection(self, collection_name: str) -> Any:
        try:
            return self.client.get_or_create_collection(name=collection_name, metadata={"hnsw:space": "cosine"})
        except Exception as exc:
            _raise_wrapped_chroma_error(exc)

    def upsert(self, collection_name: str, *, chunks: list[KnowledgeChunk], embeddings: list[list[float]]) -> int:
        if len(chunks) != len(embeddings):
            raise VectorStoreError("Chunk and embedding counts do not match.")

        collection = self._collection(collection_name)
        try:
            collection.upsert(
                ids=[chunk.chunk_id for chunk in chunks],
                documents=[chunk.text for chunk in chunks],
                embeddings=embeddings,
                metadatas=[
                    {
                        "document_id": chunk.document_id,
                        "collection_name": chunk.collection_name,
                        **chunk.metadata,
                    }
                    for chunk in chunks
                ],
            )
        except Exception as exc:
            _raise_wrapped_chroma_error(exc)
        return len(chunks)

    def query(
        self,
        collection_name: str,
        *,
        query_embedding: list[float],
        top_k: int,
        min_score: float,
    ) -> list[RetrievedKnowledgeChunk]:
        collection = self._collection(collection_name)
        try:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            _raise_wrapped_chroma_error(exc)
        documents = list((results.get("documents") or [[]])[0])
        metadatas = list((results.get("metadatas") or [[]])[0])
        distances = list((results.get("distances") or [[]])[0])
        ids = list((results.get("ids") or [[]])[0])

        matches: list[RetrievedKnowledgeChunk] = []
        for chunk_id, text, metadata, distance in zip(ids, documents, metadatas, distances, strict=False):
            score = 1.0 / (1.0 + max(float(distance or 0.0), 0.0))
            if score < min_score:
                continue
            matches.append(
                RetrievedKnowledgeChunk(
                    chunk_id=str(chunk_id or ""),
                    document_id=str((metadata or {}).get("document_id", "") or ""),
                    text=str(text or ""),
                    score=round(score, 6),
                    metadata={k: v for k, v in (metadata or {}).items() if k != "document_id"},
                )
            )
        return matches

    def count(self, collection_name: str) -> int:
        collection = self._collection(collection_name)
        try:
            return int(collection.count())
        except Exception as exc:
            _raise_wrapped_chroma_error(exc)
