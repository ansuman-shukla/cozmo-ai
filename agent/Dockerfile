FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /workspace

RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY backend/pyproject.toml backend/pyproject.toml
COPY agent/pyproject.toml agent/pyproject.toml
COPY knowledge/pyproject.toml knowledge/pyproject.toml
COPY . .

RUN uv sync --package agent --group dev

CMD ["uv", "run", "--package", "agent", "python", "agent.py", "start"]

