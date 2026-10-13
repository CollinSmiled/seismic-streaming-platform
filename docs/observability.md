# Local observability

The Python processes expose Prometheus metrics directly. Prometheus collects samples every 15 seconds; Grafana reads Prometheus and displays the provisioned operations dashboard. This keeps metrics in time series storage rather than PostgreSQL's earthquake tables.

## Health and readiness

`/health` means the process can answer HTTP. It does not check dependencies. `/ready` means the API can run `SELECT 1` against PostgreSQL, or that a worker is currently able to do useful work. A worker starts unready. The WebSocket worker becomes ready after a connection opens and returns to unready after disconnect or a Kafka delivery failure. Reconciliation becomes ready after a complete acknowledged scan; a failed scan makes it unready. The processor becomes ready after connecting to PostgreSQL and obtaining Kafka metadata; a processing failure stops it. A missing worker process is detected by Prometheus's `up` metric, since its endpoint disappears.

The API checks PostgreSQL on every `/ready` and `/metrics` request with a two-second pool timeout. Its `seismic_api_database_ready` gauge therefore reflects scrape-time database state, even if nobody calls `/ready` manually. A quiet WebSocket connection cannot prove Kafka availability until a publication is attempted, and successful reconciliation readiness does not prove a future scan will succeed. The failure counters and stale-scan alert cover those later failures.

## Metrics and logs

The application emits `seismic_api_requests_total` by route template and status class, `seismic_api_database_ready`, `seismic_source_events_total` by fixed source and outcome, `seismic_processor_records_total` by fixed outcome, `seismic_reconciliation_scans_total` by outcome, and worker readiness, failure, and last-success series. Earthquake IDs and regions never become metric labels; one label value per event would create unbounded time series. Source event counts mean Kafka acknowledgements, including overlapping FDSN replays, not unique earthquakes. Processor committed counts mean the database write and offset commit both completed.

Logs contain UTC time, severity, service, logger, and message as JSON. Detailed event IDs may appear in logs for diagnosis, but the metrics do not carry them.

## Alerts

The checked-in Prometheus rules mark targets down, API database failure, worker unready state, repeated worker failures, and a reconciliation scan gap above ten minutes. Each condition must persist for two minutes before firing. See Prometheus **Alerts** or the dashboard's firing-alert count. These local rules are visible but have no external notification receiver yet; delivery routing belongs with the production deployment. A stopped local worker will intentionally appear as a down target after two minutes.

Validate the rule syntax and failure scenarios from the repository root:

```powershell
docker compose run --rm --no-deps --entrypoint promtool prometheus check config /etc/prometheus/prometheus.yml
docker compose run --rm --no-deps --entrypoint promtool prometheus check rules /etc/prometheus/alerts.yml
docker compose run --rm --no-deps --entrypoint promtool prometheus test rules /etc/prometheus/rules.test.yml
python scripts/verify_observability.py
```

The last command requires the API running on `0.0.0.0:8000` and the monitoring containers. If the Grafana credentials or ports differ from the defaults, set `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_PORT`, and `PROMETHEUS_PORT` in that shell as well as in Compose's `.env`.
