# Cozmo Voice Platform

This repository is the implementation workspace for the Cozmo PSTN voice AI platform described in [`docs/`](docs/).

## Current status

Phase 0 scaffolding is in place:

- `backend/` holds the FastAPI control-plane service
- `agent/` holds the LiveKit worker skeleton
- `knowledge/` holds ingestion and retrieval utilities
- `contracts/` holds shared Pydantic schemas used across services
- `infra/` holds Docker Compose and observability config
- `tests/` holds shared end-to-end and load-test placeholders

## Quick start

```bash
uv sync --all-packages --dev
uv run --package backend uvicorn app.main:app --host 0.0.0.0 --port 8000
uv run --package agent python agent.py start
uv run --all-packages pytest -m unit
docker compose -f infra/docker-compose.yml config
```

## Planning docs

- [`docs/prd-cozmo.md`](docs/prd-cozmo.md)
- [`docs/platform-architecture-cozmo.md`](docs/platform-architecture-cozmo.md)
- [`docs/implementation-plan.md`](docs/implementation-plan.md)
- [`docs/todo.md`](docs/todo.md)
