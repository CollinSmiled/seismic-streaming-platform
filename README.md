# Seismic Streaming Platform

A real-time earthquake event platform being built around EMSC notifications, Kafka, PostgreSQL, a React/Mapbox map, and Prometheus/Grafana observability.

## Current status

The repository currently contains the Python API and React scaffolds plus a local Kafka/PostgreSQL Compose stack. The event pipeline and map are not connected yet.

## Requirements

- Docker Desktop or Docker Engine with Compose
- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Node.js 22.12 or newer and npm

## Local setup

From the repository root, copy `.env.example` to `.env` if you want to change the local defaults. The example password is for local development only.

```powershell
Copy-Item .env.example .env
docker compose up -d --wait kafka postgres
```

By default, the host can reach Kafka at `localhost:9092` and PostgreSQL at `localhost:5432`; `.env` can override those host ports. Containers on the Compose network will use `kafka:19092` and `postgres:5432`. Only the loopback interface exposes these ports to the host. `docker compose down` stops the services and keeps their named volumes.

If port `5432` is unavailable on your machine, set `POSTGRES_PORT=15432` in `.env` and rerun `docker compose up -d --wait kafka postgres`. PostgreSQL will then be reachable from the host at `localhost:15432`; its container address stays `postgres:5432`.

### Python API

```powershell
cd backend
uv sync --frozen --python 3.12
uv run --frozen uvicorn seismic_stream.api.app:app --reload
```

The API liveness endpoint is `http://127.0.0.1:8000/health`.

### React frontend

```powershell
cd frontend
npm ci
npm run dev
```

Vite prints the local frontend URL. The current page is a scaffold; the map is a later increment.

## Checks

```powershell
cd backend
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src tests
uv run --frozen pytest
```

```powershell
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
```

## Data source and rights

Earthquake data will come from [EMSC-CSEM SeismicPortal](https://www.seismicportal.eu/). EMSC data has separate [CC BY 4.0 attribution terms](https://www.seismicportal.eu/terms.html).

All rights reserved. No license is granted for this repository's original code.
