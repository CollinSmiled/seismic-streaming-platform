"""Read EMSC WebSocket notifications into the shared Kafka event contract."""

import argparse
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import ValidationError
from websockets.sync.client import connect

from seismic_stream.events import TOPIC_NAME, EarthquakeEvent
from seismic_stream.ingestion.emsc import (
    MAX_SOURCE_MESSAGE_BYTES,
    SourceMessageError,
    parse_emsc_notification,
)
from seismic_stream.ingestion.fixture_producer import publish_events

EMSC_WEBSOCKET_URL = "wss://www.seismicportal.eu/standing_order/websocket"
LOGGER = logging.getLogger(__name__)


def ingest_connection(url: str, publish: Callable[[EarthquakeEvent], object]) -> None:
    """Read one connection; each valid notification is acknowledged by publish."""
    with connect(
        url,
        legacy=True,
        open_timeout=10,
        ping_interval=15,
        ping_timeout=15,
        max_size=MAX_SOURCE_MESSAGE_BYTES,
        max_queue=4,
    ) as websocket:
        LOGGER.info("Connected to EMSC WebSocket")
        for raw in websocket:
            try:
                event = parse_emsc_notification(raw, ingested_at=datetime.now(UTC))
            except (SourceMessageError, ValidationError) as error:
                LOGGER.warning("Ignored invalid EMSC message: %s", error)
                continue
            publish(event)
            LOGGER.info("Kafka acknowledged EMSC event %s", event.event_id)


def main() -> None:
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
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    def publish(event: EarthquakeEvent) -> None:
        publish_events(
            [event], bootstrap_servers=args.bootstrap_server, topic=args.topic
        )

    ingest_connection(args.url, publish)


if __name__ == "__main__":
    main()
