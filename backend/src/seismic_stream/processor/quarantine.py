"""Acknowledge invalid input only after a bounded quarantine record is durable."""

import hashlib
import json
from typing import Literal

from confluent_kafka import KafkaError, Message, Producer

QUARANTINE_TOPIC = "earthquake.events.v1.quarantine"
FailureCode = Literal["missing_value", "invalid_event", "key_mismatch"]


class QuarantinePublisher:
    def __init__(self, producer: Producer, topic: str = QUARANTINE_TOPIC) -> None:
        self.producer = producer
        self.topic = topic

    def publish(self, record: Message, code: FailureCode) -> None:
        """Store a locator and hashes, not the untrusted payload or exception text."""
        payload = record.value() or b""
        key = record.key() or b""
        locator = f"{record.topic()}:{record.partition()}:{record.offset()}"
        diagnostic = {
            "schema_version": 1,
            "source_topic": record.topic(),
            "source_partition": record.partition(),
            "source_offset": record.offset(),
            "failure_code": code,
            "payload_size": len(payload),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "key_sha256": hashlib.sha256(key).hexdigest(),
        }
        acknowledged = False
        failure: KafkaError | None = None

        def on_delivery(error: KafkaError | None, _message: Message) -> None:
            nonlocal acknowledged, failure
            acknowledged = error is None
            failure = error

        self.producer.produce(
            topic=self.topic,
            key=locator.encode("utf-8"),
            value=json.dumps(
                diagnostic, sort_keys=True, separators=(",", ":")
            ).encode(),
            on_delivery=on_delivery,
        )
        remaining = self.producer.flush(15)
        if remaining:
            raise TimeoutError("quarantine record was not acknowledged")
        if failure is not None or not acknowledged:
            raise RuntimeError("quarantine delivery failed")
