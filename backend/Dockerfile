FROM ghcr.io/astral-sh/uv:0.6.3@sha256:8257f3d17fd04794feaf89d83b4ccca3b2eaa5501de9399fa53929843c0a5b55 AS uv
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_LINK_MODE=copy uv sync --frozen --no-dev --no-editable --python /usr/local/bin/python

FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
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
