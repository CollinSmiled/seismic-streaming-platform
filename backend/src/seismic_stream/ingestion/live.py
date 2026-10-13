"""Read EMSC WebSocket notifications into the shared Kafka event contract."""

import argparse
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event

from confluent_kafka import KafkaException
from pydantic import ValidationError
from websockets.exceptions import ConnectionClosed, InvalidHandshake
from websockets.sync.client import connect

from seismic_stream.events import TOPIC_NAME, EarthquakeEvent
from seismic_stream.ingestion.emsc import (
    MAX_SOURCE_MESSAGE_BYTES,
    SourceMessageError,
    parse_emsc_notification,
)
from seismic_stream.ingestion.publisher import KafkaDeliveryError, KafkaEventPublisher
from seismic_stream.observability import (
    SOURCE_EVENTS,
    WorkerStatus,
    configure_logging,
    start_worker_http,
)

EMSC_WEBSOCKET_URL = "wss://www.seismicportal.eu/standing_order/websocket"
LOGGER = logging.getLogger(__name__)


def ingest_connection(
    url: str,
    publish: Callable[[EarthquakeEvent], object],
    *,
    stop: Event | None = None,
    status: WorkerStatus | None = None,
) -> int:
    """Read one connection, pausing upstream reads until Kafka acknowledges."""
    stop = stop or Event()
    acknowledged = 0
    with connect(
        url,
        legacy=True,
        open_timeout=10,
        ping_interval=15,
        ping_timeout=15,
        close_timeout=2,
        max_size=MAX_SOURCE_MESSAGE_BYTES,
        max_queue=4,
    ) as websocket:
        LOGGER.info("Connected to EMSC WebSocket")
        if status is not None:
            status.set_ready(True)
        try:
            while not stop.is_set():
                try:
                    raw = websocket.recv(timeout=1)
                except TimeoutError:
                    continue
                except ConnectionClosed:
                    break
                try:
                    event = parse_emsc_notification(raw, ingested_at=datetime.now(UTC))
                except (SourceMessageError, ValidationError) as error:
                    SOURCE_EVENTS.labels("websocket", "invalid").inc()
                    LOGGER.warning(
                        "Ignored invalid EMSC notification: %s", type(error).__name__
                    )
                    continue
                publish(event)
                SOURCE_EVENTS.labels("websocket", "acknowledged").inc()
                if status is not None:
                    status.succeeded()
                acknowledged += 1
                LOGGER.info("Kafka acknowledged EMSC event %s", event.event_id)
        finally:
            if status is not None:
                status.set_ready(False)
    return acknowledged


def ingest_forever(
    url: str,
    publish: Callable[[EarthquakeEvent], object],
    *,
    stop: Event,
    retry_min_seconds: float = 1,
    retry_max_seconds: float = 30,
    status: WorkerStatus | None = None,
) -> None:
    """Reconnect after source or Kafka failures with a bounded exponential delay."""
    if retry_min_seconds <= 0 or retry_max_seconds < retry_min_seconds:
        raise ValueError("invalid reconnect delay range")
    delay = retry_min_seconds
    while not stop.is_set():
        try:
            acknowledged = ingest_connection(url, publish, stop=stop, status=status)
            if acknowledged:
                delay = retry_min_seconds
            if not stop.is_set():
                if status is not None:
                    status.failed()
                LOGGER.warning("EMSC WebSocket closed; reconnecting")
        except (
            OSError,
            TimeoutError,
            ConnectionClosed,
            InvalidHandshake,
            KafkaDeliveryError,
            KafkaException,
        ) as error:
            if stop.is_set():
                break
            if status is not None:
                status.failed()
            LOGGER.warning("EMSC ingestion interrupted: %s", type(error).__name__)
        if stop.wait(delay):
            break
        delay = min(delay * 2, retry_max_seconds)


def main() -> None:
    import signal

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", default=os.getenv("EMSC_WEBSOCKET_URL", EMSC_WEBSOCKET_URL)
    )
    parser.add_argument(
        "--bootstrap-server",
        default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "127.0.0.1:9092"),
    )
    parser.add_argument("--topic", default=TOPIC_NAME)
    args = parser.parse_args()
    configure_logging("websocket")

    stop = Event()

    def request_stop(_signal_number: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    publisher = KafkaEventPublisher(args.bootstrap_server, topic=args.topic)
    status = WorkerStatus("websocket")
    monitor = start_worker_http(status, port=9102)
    try:
        ingest_forever(args.url, publisher.publish, stop=stop, status=status)
    finally:
        status.set_ready(False)
        monitor.shutdown()
        monitor.server_close()
        publisher.close()


if __name__ == "__main__":
    main()
