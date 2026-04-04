"""Ingestion-job orchestration helpers."""

from dataclasses import dataclass


@dataclass(slots=True)
class IngestJobService:
    """Track queued knowledge-ingestion jobs until the real workflow lands."""

    backend_name: str = "knowledge"

    def create_job(self) -> dict[str, str]:
        return {"job_id": "pending", "backend": self.backend_name}

