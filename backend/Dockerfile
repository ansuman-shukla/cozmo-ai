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

RUN uv sync --package backend --group dev

EXPOSE 8000

CMD ["uv", "run", "--package", "backend", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

