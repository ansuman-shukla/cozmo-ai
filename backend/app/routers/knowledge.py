"""Knowledge base APIs."""

from fastapi import APIRouter, HTTPException, Request, status

from app.services.knowledge_service import (
    KnowledgeIngestRequest,
    KnowledgeQueryRequest,
    KnowledgeServiceError,
    job_to_payload,
    matches_to_payload,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_knowledge(
    request: Request,
    payload: KnowledgeIngestRequest,
) -> dict[str, object]:
    service = getattr(request.app.state, "knowledge_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="knowledge unavailable")

    try:
        job = service.ingest(payload)
    except KnowledgeServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return job_to_payload(job)


@router.get("/jobs/{job_id}")
async def get_ingest_job(request: Request, job_id: str) -> dict[str, object]:
    service = getattr(request.app.state, "knowledge_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="knowledge unavailable")

    job = service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return job_to_payload(job)


@router.post("/query")
async def query_knowledge(
    request: Request,
    payload: KnowledgeQueryRequest,
) -> dict[str, object]:
    service = getattr(request.app.state, "knowledge_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="knowledge unavailable")

    try:
        matches = service.query(
            collection_name=payload.collection_name,
            query_text=payload.query_text,
            top_k=payload.top_k,
            min_score=payload.min_score,
        )
    except KnowledgeServiceError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"matches": matches_to_payload(matches)}
