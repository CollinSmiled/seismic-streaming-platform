"""Bounded, acknowledgement-driven Kafka publication for live EMSC input."""

import time

from confluent_kafka import KafkaError, Message, Producer

from seismic_stream.events import TOPIC_NAME, EarthquakeEvent


class KafkaDeliveryError(RuntimeError):
    """A source notification was not safely acknowledged by Kafka."""


class KafkaEventPublisher:
    def __init__(
        self,
        bootstrap_servers: str,
        *,
        topic: str = TOPIC_NAME,
        delivery_timeout_seconds: float = 15,
        producer: Producer | None = None,
    ) -> None:
        if delivery_timeout_seconds <= 0:
            raise ValueError("delivery timeout must be positive")
        self.topic = topic
        self.delivery_timeout_seconds = delivery_timeout_seconds
        self.producer = producer or Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "enable.idempotence": True,
                "acks": "all",
                "message.timeout.ms": int(delivery_timeout_seconds * 1000),
                "queue.buffering.max.messages": 1000,
            }
        )

    def publish(self, event: EarthquakeEvent) -> None:
        """Read no further upstream messages until Kafka confirms this record."""
        deadline = time.monotonic() + self.delivery_timeout_seconds
        result: list[KafkaError | None] = []

        def on_delivery(error: KafkaError | None, _message: Message) -> None:
            result.append(error)

        while True:
            try:
                self.producer.produce(
                    topic=self.topic,
                    key=event.event_id.encode("utf-8"),
                    value=event.to_wire_bytes(),
                    on_delivery=on_delivery,
                )
                break
            except BufferError as error:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise KafkaDeliveryError(
                        "Kafka producer queue stayed full"
                    ) from error
                self.producer.poll(min(remaining, 0.5))

        while not result:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise KafkaDeliveryError("Kafka delivery acknowledgement timed out")
            self.producer.poll(min(remaining, 0.5))
        if result[0] is not None:
            raise KafkaDeliveryError(f"Kafka delivery failed: {result[0]}")

    def close(self) -> None:
        remaining = self.producer.flush(min(self.delivery_timeout_seconds, 5))
        if remaining:
            raise KafkaDeliveryError(
                f"{remaining} Kafka record(s) remained on shutdown"
            )
