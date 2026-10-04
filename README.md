# Seismic Streaming Platform

A real-time earthquake event platform being built around EMSC notifications, Kafka, PostgreSQL, a React/Mapbox map, and Prometheus/Grafana observability.

## Current status

The repository has a fixture-to-Kafka-to-PostgreSQL pipeline, historical and live read APIs, and a React map and event list with live change notices. Live EMSC ingestion is a future increment.

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
$env:DATABASE_URL = 'postgresql://seismic:local-dev-only@127.0.0.1:5432/seismic'
uv run --frozen uvicorn seismic_stream.api.app:app --reload
```

Set `DATABASE_URL` before starting the API to enable earthquake reads (see the processor setup below). The liveness endpoint is `http://127.0.0.1:8000/health`; historical, change, and SSE endpoints are described in [the API reference](docs/api.md).

### PostgreSQL projection and Kafka processor

Create both Kafka topics from the repository root before starting the processor:

```powershell
docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:19092 --create --if-not-exists --topic earthquake.events.v1 --partitions 1 --replication-factor 1
docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:19092 --create --if-not-exists --topic earthquake.events.v1.quarantine --partitions 1 --replication-factor 1
```

From `backend`, apply the database migration and start the processor:

```powershell
cd backend
$env:DATABASE_URL = 'postgresql://seismic:local-dev-only@127.0.0.1:5432/seismic'
uv run --frozen alembic upgrade head
uv run --frozen python -m seismic_stream.processor.worker
```

The processor keeps running and commits a Kafka offset only after the database write or quarantine publication succeeds. Use a separate terminal to publish fixtures. If you changed `POSTGRES_PORT`, change the port in `DATABASE_URL` too. The database stores one current row per EMSC ID; [persistence notes](docs/persistence.md) explain replay and revision behavior.

### Publish sample earthquakes

With Kafka running and the topics created, publish the two frozen EMSC catalogue features from `backend`:

```powershell
cd backend
uv run --frozen python -m seismic_stream.ingestion.fixture_producer --fixture tests/fixtures/emsc_catalogue_capture.json --ingested-at 2026-10-03T17:00:00Z
```

The command reports success only after Kafka acknowledges both messages. Its timestamp is fixed for reproducible fixture output; live ingestion will use the actual observation time. The Kafka key is the EMSC `unid`. See [the event contract](docs/event-contract.md) for the fields and validation rules.

To inspect the records, return to the repository root and run:

```powershell
docker compose exec -T kafka /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server kafka:19092 --topic earthquake.events.v1 --from-beginning --max-messages 2 --timeout-ms 10000 --formatter-property print.key=true
```

### React frontend

```powershell
cd frontend
npm ci
Copy-Item .env.example .env.local
# Edit .env.local and add your public Mapbox access token.
npm run dev
```

Vite prints the local frontend URL and proxies `/api` requests to `http://127.0.0.1:8000`. Start the API and processor in separate terminals after applying the migration. The list and details work without a Mapbox token; the map needs a public token in `frontend/.env.local`. The token is exposed in the browser by design, so use a URL-restricted public token for deployment. Selecting an earthquake in the list centers the map. New committed earthquakes produce a dismissible notice; revisions update the existing event. The browser catches up after reconnect, while Refresh data remains available for manual recovery.

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
