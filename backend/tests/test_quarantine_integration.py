"""Poison records must reach quarantine before their source offset advances."""

import hashlib
import json
import os
from typing import cast
from unittest.mock import Mock
from uuid import uuid4

import pytest
from confluent_kafka import (
    Consumer,
    KafkaError,
    KafkaException,
    Message,
    Producer,
    TopicPartition,
)
from confluent_kafka.admin import AdminClient, NewTopic  # type: ignore[attr-defined]

from seismic_stream.processor.quarantine import QUARANTINE_TOPIC, QuarantinePublisher
from seismic_stream.processor.store import EventStore
from seismic_stream.processor.worker import process_record

SOURCE_TOPIC = "earthquake.events.v1.poison-test"


@pytest.mark.integration
def test_invalid_record_is_acknowledged_only_after_quarantine() -> None:
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if not bootstrap:
        pytest.skip("set KAFKA_BOOTSTRAP_SERVERS to run Kafka integration tests")

    admin = AdminClient({"bootstrap.servers": bootstrap})
    for topic in (SOURCE_TOPIC, QUARANTINE_TOPIC):
        try:
            admin.create_topics([NewTopic(topic, 1, 1)])[topic].result(timeout=15)
        except KafkaException as error:
            if error.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                raise

    source = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": f"seismic-poison-test-{uuid4().hex}",
            "enable.auto.commit": False,
        }
    )
    quarantine_reader = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": f"seismic-quarantine-readback-{uuid4().hex}",
            "enable.auto.commit": False,
        }
    )
    producer = Producer({"bootstrap.servers": bootstrap, "acks": "all"})
    try:
        source_partition = TopicPartition(SOURCE_TOPIC, 0)
        quarantine_partition = TopicPartition(QUARANTINE_TOPIC, 0)
        _, source_high = source.get_watermark_offsets(source_partition, timeout=15)
        _, quarantine_high = quarantine_reader.get_watermark_offsets(
            quarantine_partition, timeout=15
        )
        source.assign([TopicPartition(SOURCE_TOPIC, 0, source_high)])
        quarantine_reader.assign([TopicPartition(QUARANTINE_TOPIC, 0, quarantine_high)])

        invalid_payload = b"{invalid-json"
        deliveries: list[KafkaError | None] = []
        producer.produce(
            topic=SOURCE_TOPIC,
            key=b"bad-event",
            value=invalid_payload,
            on_delivery=lambda error, _message: deliveries.append(error),
        )
        assert producer.flush(15) == 0
        assert deliveries == [None]

        record = source.poll(10)
        assert record is not None and record.error() is None
        store = Mock(spec=EventStore)
        process_record(
            record,
            store=cast(EventStore, store),
            consumer=source,
            quarantine=QuarantinePublisher(producer),
        )
        store.write.assert_not_called()

        quarantined: Message | None = quarantine_reader.poll(10)
        assert quarantined is not None and quarantined.error() is None
        quarantined_value = quarantined.value()
        assert quarantined_value is not None
        diagnostic = json.loads(quarantined_value)
        assert diagnostic["failure_code"] == "invalid_event"
        assert diagnostic["source_topic"] == SOURCE_TOPIC
        assert diagnostic["source_partition"] == 0
        assert diagnostic["source_offset"] == source_high
        assert (
            diagnostic["payload_sha256"] == hashlib.sha256(invalid_payload).hexdigest()
        )
        assert invalid_payload not in quarantined_value
        assert (
            source.committed([source_partition], timeout=10)[0].offset
            == source_high + 1
        )
    finally:
        source.close()
        quarantine_reader.close()
        producer.flush(15)
