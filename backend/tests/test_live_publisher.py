"""One in-flight Kafka event provides bounded backpressure to the WebSocket."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from confluent_kafka import KafkaError, Message, Producer

from seismic_stream.events import EarthquakeEvent
from seismic_stream.ingestion.fixture_producer import load_fixture
from seismic_stream.ingestion.publisher import KafkaDeliveryError, KafkaEventPublisher

CAPTURE = Path(__file__).parent / "fixtures" / "emsc_catalogue_capture.json"


class FakeProducer:
    def __init__(
        self, *, fail: bool = False, queue_full_once: bool = False, ack: bool = True
    ) -> None:
        self.fail = fail
        self.queue_full_once = queue_full_once
        self.ack = ack
        self.records: list[tuple[str, bytes, bytes]] = []
        self.callback: Callable[[KafkaError | None, Message], None] | None = None
        self.polls = 0
        self.flushed = False

    def produce(
        self,
        *,
        topic: str,
        key: bytes,
        value: bytes,
        on_delivery: Callable[[KafkaError | None, Message], None],
    ) -> None:
        if self.queue_full_once:
            self.queue_full_once = False
            raise BufferError("queue full")
        self.records.append((topic, key, value))
        self.callback = on_delivery

    def poll(self, _timeout: float) -> int:
        self.polls += 1
        if self.callback is not None and self.ack:
            callback = self.callback
            self.callback = None
            error = KafkaError(KafkaError._MSG_TIMED_OUT) if self.fail else None
            callback(error, cast(Message, None))
            return 1
        return 0

    def flush(self, _timeout: float) -> int:
        self.flushed = True
        return 0


def sample_event() -> EarthquakeEvent:
    return load_fixture(CAPTURE, ingested_at=datetime(2026, 10, 3, 17, tzinfo=UTC))[0]


def test_acknowledgement_after_bounded_queue_backpressure() -> None:
    producer = FakeProducer(queue_full_once=True)
    publisher = KafkaEventPublisher("unused", producer=cast(Producer, producer))
    event = sample_event()
    publisher.publish(event)
    publisher.close()

    assert producer.polls >= 2
    assert producer.flushed
    assert producer.records == [
        ("earthquake.events.v1", event.event_id.encode("utf-8"), event.to_wire_bytes())
    ]


def test_kafka_failure_and_missing_ack_are_not_success() -> None:
    failed = KafkaEventPublisher(
        "unused", producer=cast(Producer, FakeProducer(fail=True))
    )
    with pytest.raises(KafkaDeliveryError, match="delivery failed"):
        failed.publish(sample_event())

    missing = KafkaEventPublisher(
        "unused",
        delivery_timeout_seconds=0.01,
        producer=cast(Producer, FakeProducer(ack=False)),
    )
    with pytest.raises(KafkaDeliveryError, match="timed out"):
        missing.publish(sample_event())
