FROM ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 AS uv
FROM python:3.15-slim-bookworm@sha256:96599df822d0e1c6bb700014a05c7f3c8cabc6e0f7ff3c4f9f69cee033b4b5d9 AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_LINK_MODE=copy uv sync --frozen --no-dev --no-editable --python /usr/local/bin/python

FROM python:3.15-slim-bookworm@sha256:96599df822d0e1c6bb700014a05c7f3c8cabc6e0f7ff3c4f9f69cee033b4b5d9
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd --gid 10001 seismic && useradd --uid 10001 --gid seismic --no-create-home seismic
WORKDIR /app
COPY --from=build /app/.venv ./.venv
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/container_entrypoint.py ./
USER 10001:10001
ENTRYPOINT ["python", "/app/container_entrypoint.py"]
CMD ["uvicorn", "seismic_stream.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
