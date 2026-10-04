"""Worker status reflects injected failure and logs are machine-readable."""

import json
import logging
from urllib.error import HTTPError
from urllib.request import urlopen

from seismic_stream.observability import JsonFormatter, WorkerStatus, worker_http_server


def test_worker_health_and_readiness_follow_failures() -> None:
    status = WorkerStatus("test_worker")
    server = worker_http_server(status, port=0)
    from threading import Thread

    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(f"{base}/health") as response:
            assert response.status == 200
        try:
            urlopen(f"{base}/ready")
            assert False, "unready worker should return 503"
        except HTTPError as error:
            assert error.code == 503
        status.set_ready(True)
        with urlopen(f"{base}/ready") as response:
            assert response.status == 200
        status.failed()
        with urlopen(f"{base}/metrics") as response:
            metrics = response.read().decode()
        assert 'seismic_worker_ready{service="test_worker"} 0.0' in metrics
        assert 'seismic_worker_failures_total{service="test_worker"} 1.0' in metrics
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_json_log_includes_service_and_utc_timestamp() -> None:
    record = logging.LogRecord(
        "seismic.test", logging.WARNING, __file__, 1, "connection lost", (), None
    )
    log = json.loads(JsonFormatter("websocket").format(record))
    assert log["timestamp"].endswith("+00:00")
    assert log["service"] == "websocket"
    assert log["level"] == "WARNING"
    assert log["message"] == "connection lost"
