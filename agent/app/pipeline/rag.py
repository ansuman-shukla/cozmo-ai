"""Retrieval adapter helpers."""

from dataclasses import dataclass
from typing import Mapping, Sequence


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
