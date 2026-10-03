"""Runs against the Compose broker only when its address is supplied."""

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from confluent_kafka import (
    Consumer,
    KafkaError,
    KafkaException,
    Message,
    TopicPartition,
)
from confluent_kafka.admin import AdminClient, NewTopic  # type: ignore[attr-defined]

from seismic_stream.events import EarthquakeEvent
from seismic_stream.ingestion.fixture_producer import load_fixture, publish_events

TOPIC = "earthquake.events.v1.integration"
CAPTURE = Path(__file__).parent / "fixtures" / "emsc_catalogue_capture.json"


@pytest.mark.integration
def test_fixture_records_can_be_consumed_from_kafka() -> None:
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if not bootstrap:
        pytest.skip("set KAFKA_BOOTSTRAP_SERVERS to run the Kafka integration test")

    admin = AdminClient({"bootstrap.servers": bootstrap})
    future = admin.create_topics([NewTopic(TOPIC, 1, 1)])[TOPIC]
    try:
        future.result(timeout=15)
    except KafkaException as error:
        if error.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
            raise

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": "seismic-fixture-readback",
            "enable.auto.commit": False,
        }
    )
    try:
        partition = TopicPartition(TOPIC, 0)
        _, high = consumer.get_watermark_offsets(partition, timeout=15)
        consumer.assign([TopicPartition(TOPIC, 0, high)])
        events = load_fixture(
            CAPTURE, ingested_at=datetime(2026, 10, 3, 17, 0, tzinfo=UTC)
        )
        assert publish_events(events, bootstrap_servers=bootstrap, topic=TOPIC) == 2

        records: list[Message] = []
        deadline = time.monotonic() + 15
        while len(records) < 2 and time.monotonic() < deadline:
            record = consumer.poll(1)
            if record is not None:
                if record.error():
                    raise KafkaException(record.error())
                records.append(record)

        assert len(records) == 2
        assert [record.key() for record in records] == [
            event.event_id.encode("utf-8") for event in events
        ]
        decoded = []
        for record in records:
            value = record.value()
            assert value is not None
            decoded.append(EarthquakeEvent.from_wire_bytes(value))
        assert decoded == events
        assert all(event.schema_version == 1 for event in decoded)
    finally:
        consumer.close()
