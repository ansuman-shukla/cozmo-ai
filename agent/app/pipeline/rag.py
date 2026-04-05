"""Retrieval adapter helpers."""

from dataclasses import dataclass
import logging
from typing import Any, Mapping, Sequence

import httpx

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A normalized knowledge chunk used during grounded response generation."""

    chunk_id: str
    text: str
    score: float


class RagAdapter:
    """Normalize and filter retrieval hits for prompt construction."""

    def __init__(self, *, top_k: int = 3, min_score: float = 0.35) -> None:
        self.top_k = top_k
        self.min_score = min_score

    def normalize_hits(self, hits: Sequence[RetrievedChunk | Mapping[str, object]]) -> list[RetrievedChunk]:
        """Convert raw retrieval hits into filtered, score-sorted chunks."""

        normalized: list[RetrievedChunk] = []
        for hit in hits:
            if isinstance(hit, RetrievedChunk):
                chunk = hit
            else:
                chunk = RetrievedChunk(
                    chunk_id=str(hit.get("chunk_id", "") or "").strip(),
                    text=str(hit.get("text", "") or "").strip(),
                    score=float(hit.get("score", 0.0) or 0.0),
                )

            if not chunk.chunk_id or not chunk.text or chunk.score < self.min_score:
                continue
            normalized.append(chunk)

        normalized.sort(key=lambda item: item.score, reverse=True)
        return normalized[: self.top_k]


@dataclass(slots=True)
class BackendKnowledgeRetriever:
    """Query the backend control plane for grounded knowledge chunks."""

    base_url: str
    top_k: int = 3
    min_score: float = 0.35
    timeout_ms: int = 200

    @classmethod
    def from_settings(cls, settings: Any) -> "BackendKnowledgeRetriever":
        return cls(
            base_url=str(getattr(settings, "backend_base_url", "http://127.0.0.1:8000")),
            top_k=int(getattr(settings, "kb_top_k", 3)),
            min_score=float(getattr(settings, "kb_min_score", 0.35)),
            timeout_ms=int(getattr(settings, "timeout_kb_ms", 200)),
        )

    async def retrieve(
        self,
        *,
        collection_name: str,
        query_text: str,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> list[RetrievedChunk]:
        normalized_collection = str(collection_name or "").strip()
        normalized_query = " ".join(str(query_text or "").split()).strip()
        if not normalized_collection or not normalized_query:
            return []

        endpoint = f"{self.base_url.rstrip('/')}/knowledge/query"
        payload = {
            "collection_name": normalized_collection,
            "query_text": normalized_query,
            "top_k": int(top_k or self.top_k),
            "min_score": float(self.min_score if min_score is None else min_score),
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_ms / 1000.0) as client:
                response = await client.post(endpoint, json=payload)
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            LOGGER.warning(
                "knowledge retrieval failed for live turn",
                extra={
                    "endpoint": endpoint,
                    "collection_name": normalized_collection,
                    "query_text": normalized_query,
                    "error": str(exc),
                },
            )
            return []

        matches = body.get("matches", [])
        if not isinstance(matches, list):
            return []
        return RagAdapter(
            top_k=payload["top_k"],
            min_score=payload["min_score"],
        ).normalize_hits(matches)
