"""Agent configuration APIs."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request, status

from cozmo_contracts.models import AgentConfigRecord

from app.services.agent_config_service import AgentConfigService

router = APIRouter(prefix="/agents", tags=["agents"])


def get_agent_config_service(request: Request) -> AgentConfigService:
    """Return the agent-config service from app state or raise a backend readiness error."""

    agent_config_service = getattr(request.app.state, "agent_config_service", None)
    if agent_config_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent config storage is not available",
        )
    return agent_config_service


@router.get("", response_model=dict[str, list[AgentConfigRecord]])
async def list_agents(
    request: Request,
    active_only: bool | None = Query(default=None),
) -> dict[str, list[AgentConfigRecord]]:
    agent_config_service = get_agent_config_service(request)
    return {"items": agent_config_service.list_agent_configs(active_only=active_only)}


@router.get("/{config_id}", response_model=AgentConfigRecord)
async def get_agent(request: Request, config_id: str) -> AgentConfigRecord:
    agent_config_service = get_agent_config_service(request)
    record = agent_config_service.get_agent_config(config_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent config not found")
    return record


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AgentConfigRecord)
async def create_agent(request: Request, payload: AgentConfigRecord) -> AgentConfigRecord:
    agent_config_service = get_agent_config_service(request)
    return agent_config_service.upsert_agent_config(payload)


@router.put("/{config_id}", response_model=AgentConfigRecord)
async def upsert_agent(request: Request, config_id: str, payload: AgentConfigRecord) -> AgentConfigRecord:
    if payload.config_id != config_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Route config_id must match request body config_id",
        )
    agent_config_service = get_agent_config_service(request)
    updated_payload = payload.model_copy(update={"updated_at": datetime.now(UTC)})
    return agent_config_service.upsert_agent_config(updated_payload)
