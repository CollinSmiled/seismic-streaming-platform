"""Recover missed WebSocket notifications from EMSC's FDSN catalogue."""

import argparse
import json
import logging
import os
import signal
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import Any, Protocol

import httpx
import psycopg
from pydantic import ValidationError

from seismic_stream.events import EarthquakeEvent
from seismic_stream.ingestion.checkpoint import (
    ReconciliationBusy,
    exclusive_checkpoint,
)
from seismic_stream.ingestion.emsc import SourceMessageError, parse_emsc_feature
from seismic_stream.ingestion.publisher import KafkaDeliveryError, KafkaEventPublisher
from seismic_stream.observability import (
    RECONCILIATION_SCANS,
    SOURCE_EVENTS,
    WorkerStatus,
    configure_logging,
    start_worker_http,
)

FDSN_QUERY_URL = "https://www.seismicportal.eu/fdsnws/event/1/query"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_EVENTS = 5000
OVERLAP = timedelta(minutes=15)
INITIAL_LOOKBACK = timedelta(hours=1)
LOGGER = logging.getLogger(__name__)


class Checkpoint(Protocol):
    def load(self) -> datetime | None: ...
    def save(self, scanned_at: datetime) -> None: ...


class ReconciliationError(RuntimeError):
    """A scan could not safely advance its checkpoint."""


class ReconciliationInterrupted(ReconciliationError):
    """Shutdown interrupted a scan before all events were acknowledged."""


def fetch_features(
    client: httpx.Client, *, url: str, updated_after: datetime, max_events: int
) -> list[Any]:
    if not 1 <= max_events <= 19999:
        raise ValueError("max_events must be between 1 and 19999")
    params = {
        "format": "json",
        "catalog": "EMSC-RTS",
        "nodata": "204",
        "updatedafter": updated_after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f"),
        "limit": str(max_events + 1),
    }
    started = time.monotonic()
    with client.stream("GET", url, params=params) as response:
        if response.status_code == 204:
            return []
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES or time.monotonic() - started > 30:
                raise ReconciliationError(
                    "FDSN response exceeded its size or time limit"
                )
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReconciliationError("FDSN response is not valid JSON") from error
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ReconciliationError("FDSN response is not a FeatureCollection")
    features = payload.get("features")
    if not isinstance(features, list):
        raise ReconciliationError("FDSN response has no feature list")
    if len(features) > max_events:
        raise ReconciliationError(
            "FDSN result exceeds max_events; checkpoint unchanged"
        )
    return features


def reconcile_once(
    checkpoint: Checkpoint,
    client: httpx.Client,
    publish: Callable[[EarthquakeEvent], object],
    *,
    now: datetime,
    url: str = FDSN_QUERY_URL,
    max_events: int = DEFAULT_MAX_EVENTS,
    stop: Event | None = None,
) -> int:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("scan time needs a UTC offset")
    now = now.astimezone(UTC)
    previous = checkpoint.load()
    updated_after = (
        previous.astimezone(UTC) - OVERLAP
        if previous is not None
        else now - INITIAL_LOOKBACK
    )
    features = fetch_features(
        client, url=url, updated_after=updated_after, max_events=max_events
    )
    count = 0
    for feature in features:
        if stop is not None and stop.is_set():
            raise ReconciliationInterrupted("scan stopped before checkpoint commit")
        try:
            event = parse_emsc_feature(feature, ingested_at=datetime.now(UTC))
        except (SourceMessageError, ValidationError) as error:
            raise ReconciliationError("FDSN returned an invalid event") from error
        publish(event)
        SOURCE_EVENTS.labels("fdsn", "acknowledged").inc()
        count += 1
    if stop is not None and stop.is_set():
        raise ReconciliationInterrupted("scan stopped before checkpoint commit")
    checkpoint.save(now)
    return count


def run_forever(
    database_url: str,
    publisher: KafkaEventPublisher,
    *,
    stop: Event,
    url: str = FDSN_QUERY_URL,
    interval_seconds: float = 60,
    max_events: int = DEFAULT_MAX_EVENTS,
    once: bool = False,
    status: WorkerStatus | None = None,
) -> None:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive")
    with httpx.Client(timeout=10, follow_redirects=True) as client:
        while not stop.is_set():
            try:
                with exclusive_checkpoint(database_url) as checkpoint:
                    count = reconcile_once(
                        checkpoint,
                        client,
                        publisher.publish,
                        now=datetime.now(UTC),
                        url=url,
                        max_events=max_events,
                        stop=stop,
                    )
                LOGGER.info("FDSN reconciliation acknowledged %d events", count)
                RECONCILIATION_SCANS.labels("success").inc()
                if status is not None:
                    status.succeeded()
                    status.set_ready(True)
            except ReconciliationInterrupted:
                break
            except (
                httpx.HTTPError,
                psycopg.Error,
                ReconciliationBusy,
                ReconciliationError,
                KafkaDeliveryError,
            ) as error:
                RECONCILIATION_SCANS.labels("failure").inc()
                if status is not None:
                    status.failed()
                LOGGER.warning("FDSN reconciliation failed: %s", type(error).__name__)
                if once:
                    raise
            if once or stop.wait(interval_seconds):
                break


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("FDSN_QUERY_URL", FDSN_QUERY_URL))
    parser.add_argument(
        "--bootstrap-server",
        default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092"),
    )
    parser.add_argument("--interval-seconds", type=float, default=60)
    parser.add_argument("--max-events", type=int, default=DEFAULT_MAX_EVENTS)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required")
    configure_logging("reconciliation")
    stop = Event()

    def request_stop(_signal_number: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    publisher = KafkaEventPublisher(args.bootstrap_server)
    status = WorkerStatus("reconciliation")
    monitor = start_worker_http(status, port=9103)
    try:
        run_forever(
            database_url,
            publisher,
            stop=stop,
            url=args.url,
            interval_seconds=args.interval_seconds,
            max_events=args.max_events,
            once=args.once,
            status=status,
        )
    finally:
        status.set_ready(False)
        monitor.shutdown()
        monitor.server_close()
        publisher.close()


if __name__ == "__main__":
    main()
