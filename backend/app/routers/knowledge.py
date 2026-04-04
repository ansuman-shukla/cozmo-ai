"""Knowledge base APIs."""

from fastapi import APIRouter, status

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_knowledge() -> dict[str, str]:
    return {"status": "queued"}


@router.get("/jobs/{job_id}")
async def get_ingest_job(job_id: str) -> dict[str, str]:
    return {"job_id": job_id, "status": "pending"}


@router.post("/query")
async def query_knowledge() -> dict[str, list[str]]:
    return {"matches": []}

