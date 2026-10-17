FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv
FROM python:3.14-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83 AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_LINK_MODE=copy uv sync --frozen --no-dev --no-editable --python /usr/local/bin/python

FROM python:3.14-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83
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
