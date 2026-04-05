.PHONY: sync lock lint unit integration e2e load backend agent compose-config up down

sync:
	uv sync --all-packages --dev

lock:
	uv lock

lint:
	uv run --all-packages ruff check .

unit:
	uv run --all-packages pytest -m unit

integration:
	uv run --all-packages pytest -m integration

e2e:
	uv run --all-packages pytest tests/e2e

load:
	uv run python -m tests.load.runner --profiles tests/load/profiles.json --output-dir artifacts/load

backend:
	uv run --directory backend uvicorn app.main:app --host 0.0.0.0 --port 8000

agent:
	uv run --directory agent python agent.py

compose-config:
	docker compose -f infra/docker-compose.yml config

up:
	docker compose -f infra/docker-compose.yml up --build

down:
	docker compose -f infra/docker-compose.yml down
