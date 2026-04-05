"""Embedding adapters for vector retrieval."""

from __future__ import annotations

import json
from math import sqrt
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class EmbeddingAdapterError(RuntimeError):
    """Raised when embeddings cannot be generated."""


class EmbeddingAdapter:
    """Generate embeddings through a provider or a local hashed fallback."""

    def __init__(
        self,
        *,
        model_name: str,
        openai_api_key: str | None = None,
        dimensions: int = 256,
    ) -> None:
        self.model_name = model_name
        self.openai_api_key = openai_api_key
        self.dimensions = dimensions

    def _normalize(self, vector: list[float]) -> list[float]:
        norm = sqrt(sum(value * value for value in vector))
        if norm <= 0:
            return vector
        return [value / norm for value in vector]

    def _local_hash_embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in str(text).lower().split():
            slot = hash(token) % self.dimensions
            vector[slot] += 1.0
        return self._normalize(vector)

    def _openai_embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        if not self.openai_api_key:
            raise EmbeddingAdapterError("OpenAI API key is required for text-embedding-3 models.")

        payload = json.dumps(
            {
                "input": list(texts),
                "model": self.model_name,
                "encoding_format": "float",
            }
        ).encode("utf-8")
        request = Request(
            "https://api.openai.com/v1/embeddings",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise EmbeddingAdapterError(f"OpenAI embeddings request failed: {detail}") from exc
        except URLError as exc:
            raise EmbeddingAdapterError("OpenAI embeddings request failed to connect.") from exc

        vectors = [item.get("embedding", []) for item in body.get("data", [])]
        if len(vectors) != len(texts):
            raise EmbeddingAdapterError("OpenAI embeddings response length mismatch.")
        return [[float(value) for value in vector] for vector in vectors]

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts."""

        normalized_texts = [str(text).strip() for text in texts]
        if any(not text for text in normalized_texts):
            raise EmbeddingAdapterError("Embedding input texts must be non-empty.")

        if self.model_name.startswith("text-embedding-3") and self.openai_api_key:
            return self._openai_embed_many(normalized_texts)
        return [self._local_hash_embed(text) for text in normalized_texts]

    def embed(self, text: str) -> list[float]:
        """Embed one text."""

        return self.embed_many([text])[0]
