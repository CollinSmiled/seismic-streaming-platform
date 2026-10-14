# Reproduce and check the pipeline

This is a local release rehearsal for the current source-based platform. It uses frozen EMSC fixtures; no real earthquake notification is needed. CI runs the same backend integration and browser checks on disposable Kafka and PostgreSQL services.

## Checks and fault evidence

| Path or fault | Check | Expected result |
| --- | --- | --- |
| WebSocket → Kafka → processor → PostgreSQL → API | `test_end_to_end_integration.py` | The captured event appears in the historical API. |
| Database write failure before offset commit | Same test | Offset stays uncommitted; replay persists the event once. |
| Newer WebSocket revision | Same test | Magnitude changes in one row and `/changes` reports an update. |
| Missed WebSocket event recovered by FDSN | Same test | The catalogue scan sends it through Kafka; a repeat scan adds no current row or change cursor. |
| Invalid Kafka record | `test_quarantine_integration.py` | Quarantine acknowledgement precedes source offset commit. |
| Failed FDSN publish or invalid catalogue feature | `test_reconcile.py` and `test_reconcile_integration.py` | Checkpoint stays put, then replay recovers. |
| WebSocket disconnect and Kafka outage | `test_live_ingestion.py` | Bounded reconnect succeeds without an unbounded queue. |
| API/database outage | `test_api_integration.py`, `test_health.py` | Readiness and reads return 503 while unavailable. |
| Browser through API, plus a new Kafka event | `frontend/e2e/pipeline.spec.ts` | React shows the fixture, then its live notice opens the new event. |
| Prometheus/Grafana configuration and alerts | `promtool` rule tests and `scripts/verify_observability.py` | Failure scenarios fire after their hold period; dashboard queries run. |

The backend test uses a temporary database and Kafka topic, then removes both. It injects a database write exception at the store boundary to test the offset rule without stopping a shared PostgreSQL container. The browser check uses a dedicated topic and database in the local instructions below. Frontend component tests separately cover list selection, API errors, reconnect catch-up, and map behavior.

## Run backend recovery checks

From the repository root on a clean checkout, start Docker Desktop or Docker Engine, then:

```powershell
docker compose up -d --wait kafka postgres
cd backend
uv sync --frozen --python 3.12
$env:KAFKA_BOOTSTRAP_SERVERS = '127.0.0.1:9092'
$env:DATABASE_URL = 'postgresql://seismic:local-dev-only@127.0.0.1:5432/seismic'
uv run --frozen pytest -q
```

The environment variables matter: without them, integration tests are skipped. The end-to-end test should report one pass when run alone with `uv run --frozen pytest -q tests/test_end_to_end_integration.py`. The full backend suite also covers parsing, migration rollback, API validation, offsets, quarantine, and recovery. If port `5432` is occupied, set `POSTGRES_PORT` in `.env` and use the same host port in `DATABASE_URL`.

## Run the browser check locally

Create a dedicated database and topic from the repository root. The names below are for this rehearsal and should not be reused for application data:

```powershell
docker compose exec -T postgres psql -U seismic -d seismic -c 'CREATE DATABASE seismic_browser_release_test'
docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:19092 --create --if-not-exists --topic earthquake.events.v1.browser-release-test --partitions 1 --replication-factor 1
```

In a `backend` terminal, install dependencies, migrate, and publish the two captured events:

```powershell
$env:DATABASE_URL = 'postgresql://seismic:local-dev-only@127.0.0.1:5432/seismic_browser_release_test'
uv sync --frozen --python 3.12
uv run --frozen alembic upgrade head
uv run --frozen python -m seismic_stream.ingestion.fixture_producer --fixture tests/fixtures/emsc_catalogue_capture.json --ingested-at 2026-10-03T17:00:00Z --topic earthquake.events.v1.browser-release-test
```

Keep three terminals running: the processor and API from `backend`, and Vite from `frontend`:

```powershell
# backend processor terminal
$env:DATABASE_URL = 'postgresql://seismic:local-dev-only@127.0.0.1:5432/seismic_browser_release_test'
uv run --frozen python -m seismic_stream.processor.worker --topic earthquake.events.v1.browser-release-test
```

```powershell
# backend API terminal
$env:DATABASE_URL = 'postgresql://seismic:local-dev-only@127.0.0.1:5432/seismic_browser_release_test'
uv run --frozen uvicorn seismic_stream.api.app:app --host 127.0.0.1 --port 8000
```

```powershell
# frontend Vite terminal
npm ci
node node_modules/vite/bin/vite.js --host=127.0.0.1 --port=5173
```

In a fourth `frontend` terminal, install Playwright's headless Chromium once and run the check:

```powershell
npx playwright install --only-shell chromium
$env:E2E_KAFKA_TOPIC = 'earthquake.events.v1.browser-release-test'
$env:KAFKA_BOOTSTRAP_SERVERS = '127.0.0.1:9092'
npm run test:e2e
```

The test publishes one additional unique event, waits for the SSE notice, and opens its details. Stop the three running processes with Ctrl+C when finished. To remove only the dedicated rehearsal data, run these commands from the repository root:

```powershell
docker compose exec -T postgres psql -U seismic -d seismic -c 'DROP DATABASE seismic_browser_release_test WITH (FORCE)'
docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:19092 --delete --topic earthquake.events.v1.browser-release-test
```

`docker compose down` stops shared containers while preserving their volumes.

## Current limits

- The projection keeps one current revision per EMSC ID; it is not a historical revision archive. Deletions are not represented.
- WebSocket notifications missed during an outage depend on FDSN reconciliation. The first scan looks back one hour, later scans overlap by 15 minutes, and a very late catalogue update can still escape that window.
- A quiet WebSocket cannot prove Kafka availability until it publishes. Prometheus alerts are visible locally, but no external notification receiver is configured.
- CI runs the browser test without a Mapbox token, so it checks the event list, details, and live notice rather than rendered map tiles. The map component has its own tests; visual tiles need a public Mapbox token and manual review.
- A real EMSC notification cannot be scheduled for CI. The upstream WebSocket handshake and an actual incoming event remain manual checks.
- The [production package rehearsal](deployment.md) checks containers, HTTPS, protected Grafana, persistence and database backup restoration. Public VM deployment, external backups, approval and rollback automation remain pending.
