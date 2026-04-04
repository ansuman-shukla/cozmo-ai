"""Knowledge retrieval helpers."""

from dataclasses import dataclass


@dataclass(slots=True)
class KnowledgeService:
    """Placeholder service for knowledge queries."""

    endpoint: str

    def ping(self) -> dict[str, str]:
        return {"endpoint": self.endpoint, "status": "placeholder"}

