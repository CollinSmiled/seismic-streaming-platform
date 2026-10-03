"""Publish a frozen EMSC catalogue sample to Kafka for development and CI."""

import argparse
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from confluent_kafka import KafkaError, Message, Producer

from seismic_stream.events import TOPIC_NAME, EarthquakeEvent
from seismic_stream.ingestion.emsc import parse_emsc_feature

MAX_FIXTURE_BYTES = 256 * 1024
MAX_FIXTURE_EVENTS = 100


def load_fixture(path: Path, *, ingested_at: datetime) -> list[EarthquakeEvent]:
    if path.stat().st_size > MAX_FIXTURE_BYTES:
        raise ValueError("fixture exceeds the size limit")
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise ValueError("fixture must be an EMSC FeatureCollection")
    features = payload.get("features")
    if not isinstance(features, list) or not 1 <= len(features) <= MAX_FIXTURE_EVENTS:
        raise ValueError("fixture must contain 1 to 100 features")
    return [
        parse_emsc_feature(feature, ingested_at=ingested_at) for feature in features
    ]


def publish_events(
    events: Sequence[EarthquakeEvent],
    *,
    bootstrap_servers: str,
    topic: str = TOPIC_NAME,
    delivery_timeout_seconds: float = 15,
) -> int:
    """Return only after Kafka confirms every fixture record."""
    if not events:
        raise ValueError("there are no events to publish")
    producer = Producer(
        {
            "bootstrap.servers": bootstrap_servers,
            "enable.idempotence": True,
            "acks": "all",
            "message.timeout.ms": int(delivery_timeout_seconds * 1000),
        }
    )
    acknowledged = 0
    failures: list[str] = []

    def on_delivery(error: KafkaError | None, _message: Message) -> None:
        nonlocal acknowledged
        if error is None:
            acknowledged += 1
        else:
            failures.append(str(error))

    for event in events:
        producer.produce(
            topic=topic,
            key=event.event_id.encode("utf-8"),
            value=event.to_wire_bytes(),
            on_delivery=on_delivery,
        )
    remaining = producer.flush(delivery_timeout_seconds)
    if remaining:
        raise TimeoutError(f"{remaining} Kafka record(s) were not acknowledged")
    if failures:
        raise RuntimeError(f"Kafka delivery failed: {failures[0]}")
    if acknowledged != len(events):
        raise RuntimeError("Kafka did not acknowledge every fixture record")
    return acknowledged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--ingested-at", required=True, help="UTC ISO 8601 timestamp")
    parser.add_argument("--bootstrap-server", default="127.0.0.1:9092")
    parser.add_argument("--topic", default=TOPIC_NAME)
    args = parser.parse_args()
    ingested_at = datetime.fromisoformat(args.ingested_at)
    events = load_fixture(args.fixture, ingested_at=ingested_at)
    count = publish_events(
        events, bootstrap_servers=args.bootstrap_server, topic=args.topic
    )
    print(f"Kafka acknowledged {count} events on {args.topic}")


if __name__ == "__main__":
    main()
