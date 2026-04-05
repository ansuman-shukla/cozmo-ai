"""Ingestion-job orchestration helpers."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
from threading import Lock
from uuid import uuid4

KNOWLEDGE_ROOT = Path(__file__).resolve().parents[3] / "knowledge"
if str(KNOWLEDGE_ROOT) not in sys.path:
    sys.path.insert(0, str(KNOWLEDGE_ROOT))

from cozmo_knowledge.models import IngestJobRecord


class IngestJobService:
    """Track knowledge-ingestion job state transitions in memory."""

    def __init__(self) -> None:
        self._jobs: dict[str, IngestJobRecord] = {}
        self._lock = Lock()

    def create_job(self, *, collection_name: str) -> IngestJobRecord:
        """Create a queued job record."""

        record = IngestJobRecord(
            job_id=f"kb-{uuid4().hex[:12]}",
            collection_name=collection_name,
            status="queued",
        )
        with self._lock:
            self._jobs[record.job_id] = record
        return record

    def mark_running(self, job_id: str) -> IngestJobRecord:
        """Advance a job into the running state."""

        with self._lock:
            record = self._jobs[job_id]
            updated = replace(record, status="running")
            self._jobs[job_id] = updated
            return updated

    def mark_completed(
        self,
        job_id: str,
        *,
        document_count: int,
        chunk_count: int,
    ) -> IngestJobRecord:
        """Mark a job successful with counts."""

        with self._lock:
            record = self._jobs[job_id]
            updated = replace(
                record,
                status="completed",
                document_count=document_count,
                chunk_count=chunk_count,
            )
            self._jobs[job_id] = updated
            return updated

    def mark_failed(self, job_id: str, *, error: str) -> IngestJobRecord:
        """Mark a job failed."""

        with self._lock:
            record = self._jobs[job_id]
            updated = replace(record, status="failed", error=error)
            self._jobs[job_id] = updated
            return updated

    def get_job(self, job_id: str) -> IngestJobRecord | None:
        """Return one job by id."""

        with self._lock:
            return self._jobs.get(job_id)
