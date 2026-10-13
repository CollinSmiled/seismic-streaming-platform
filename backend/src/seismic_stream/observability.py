"""Shared structured logs and low-cardinality operational metrics."""

import json
import logging
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

SOURCE_EVENTS = Counter(
    "seismic_source_events_total",
    "Source events processed by the ingestion workers",
    ["source", "outcome"],
)
WORKER_FAILURES = Counter(
    "seismic_worker_failures_total", "Worker operation failures", ["service"]
)
PROCESSOR_RECORDS = Counter(
    "seismic_processor_records_total",
    "Kafka records handled by the processor",
    ["outcome"],
)
RECONCILIATION_SCANS = Counter(
    "seismic_reconciliation_scans_total", "FDSN scans", ["outcome"]
)
LAST_SUCCESS = Gauge(
    "seismic_worker_last_success_unixtime",
    "Unix time of the last successful worker operation",
    ["service"],
)
WORKER_READY = Gauge(
    "seismic_worker_ready", "Whether a worker can currently do useful work", ["service"]
)
API_REQUESTS = Counter(
    "seismic_api_requests_total",
    "API responses by route and status class",
    ["route", "status_class"],
)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, str] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(service: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True


class WorkerStatus:
    """Process-local readiness; liveness is the responding HTTP server itself."""

    def __init__(self, service: str) -> None:
        self.service = service
        self._ready = False
        self._lock = Lock()
        WORKER_READY.labels(service).set(0)
        LAST_SUCCESS.labels(service).set(0)
        WORKER_FAILURES.labels(service)

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._ready

    def set_ready(self, ready: bool) -> None:
        with self._lock:
            self._ready = ready
            WORKER_READY.labels(self.service).set(int(ready))

    def succeeded(self) -> None:
        LAST_SUCCESS.labels(self.service).set_to_current_time()

    def failed(self) -> None:
        WORKER_FAILURES.labels(self.service).inc()
        self.set_ready(False)


def worker_http_server(
    status: WorkerStatus, *, host: str = "127.0.0.1", port: int
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                code, body, mime = 200, b'{"status":"ok"}', "application/json"
            elif self.path == "/ready":
                code = 200 if status.ready else 503
                body = (
                    b'{"status":"ready"}' if status.ready else b'{"status":"unready"}'
                )
                mime = "application/json"
            elif self.path == "/metrics":
                code, body, mime = 200, generate_latest(), CONTENT_TYPE_LATEST
            else:
                code, body, mime = 404, b"Not found", "text/plain"
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


def start_worker_http(status: WorkerStatus, *, port: int) -> ThreadingHTTPServer:
    server = worker_http_server(status, host="0.0.0.0", port=port)
    Thread(target=server.serve_forever, daemon=True, name="observability-http").start()
    return server
