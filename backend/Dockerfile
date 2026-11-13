FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app/backend
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/mcw ./mcw
RUN uv sync --frozen --no-dev
COPY ontology /app/ontology
COPY fixtures /app/fixtures
ENV MCW_ONTOLOGY_PATH=/app/ontology/mcw.ttl MCW_FIXTURES_DIR=/app/fixtures
EXPOSE 8000
CMD ["uvicorn", "mcw.main:app", "--host", "0.0.0.0", "--port", "8000"]
