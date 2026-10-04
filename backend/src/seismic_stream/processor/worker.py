"""Consume validated Kafka records and advance offsets after DB commits."""

import argparse
import logging
import os

from confluent_kafka import Consumer, KafkaError, KafkaException, Message, Producer
from psycopg_pool import ConnectionPool
from pydantic import ValidationError

from seismic_stream.events import TOPIC_NAME, EarthquakeEvent
from seismic_stream.observability import (
    PROCESSOR_RECORDS,
    WorkerStatus,
    configure_logging,
    start_worker_http,
)
from seismic_stream.processor.quarantine import QuarantinePublisher
from seismic_stream.processor.store import EventStore

LOGGER = logging.getLogger(__name__)


def process_record(
    record: Message,
    *,
    store: EventStore,
    consumer: Consumer,
    quarantine: QuarantinePublisher | None = None,
) -> None:
    payload = record.value()
    if payload is None:
        if quarantine is None:
            raise ValueError("Kafka record has no value")
        quarantine.publish(record, "missing_value")
        consumer.commit(message=record, asynchronous=False)
        PROCESSOR_RECORDS.labels("quarantined").inc()
        return
    try:
        event = EarthquakeEvent.from_wire_bytes(payload)
    except (ValueError, ValidationError):
        if quarantine is None:
            raise
        quarantine.publish(record, "invalid_event")
        consumer.commit(message=record, asynchronous=False)
        PROCESSOR_RECORDS.labels("quarantined").inc()
        return
    if record.key() != event.event_id.encode("utf-8"):
        if quarantine is None:
            raise ValueError("Kafka key does not match EMSC event ID")
        quarantine.publish(record, "key_mismatch")
        consumer.commit(message=record, asynchronous=False)
        PROCESSOR_RECORDS.labels("quarantined").inc()
        return
    store.write(event)
    consumer.commit(message=record, asynchronous=False)
    PROCESSOR_RECORDS.labels("committed").inc()


def run(
    *,
    bootstrap_server: str,
    database_url: str,
    topic: str,
    status: WorkerStatus | None = None,
) -> None:
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_server,
            "group.id": "seismic-processor-v1",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    producer = Producer(
        {
            "bootstrap.servers": bootstrap_server,
            "enable.idempotence": True,
            "acks": "all",
            "message.timeout.ms": 15000,
        }
    )
    quarantine = QuarantinePublisher(producer)
    try:
        with ConnectionPool(database_url, min_size=1, max_size=4) as pool:
            pool.wait(timeout=5)
            store = EventStore(pool)
            consumer.list_topics(timeout=5)
            consumer.subscribe([topic])
            if status is not None:
                status.set_ready(True)
            while True:
                record = consumer.poll(1)
                if record is None:
                    continue
                error = record.error()
                if error is not None:
                    if error.code() == KafkaError._PARTITION_EOF:
                        continue
                    raise KafkaException(error)
                process_record(
                    record, store=store, consumer=consumer, quarantine=quarantine
                )
                if status is not None:
                    status.succeeded()
    except Exception:
        if status is not None:
            status.failed()
        raise
    finally:
        if status is not None:
            status.set_ready(False)
        consumer.close()
        producer.flush(15)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-server", default="127.0.0.1:9092")
    parser.add_argument("--topic", default=TOPIC_NAME)
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required")
    configure_logging("processor")
    status = WorkerStatus("processor")
    monitor = start_worker_http(status, port=9101)
    try:
        run(
            bootstrap_server=args.bootstrap_server,
            database_url=database_url,
            topic=args.topic,
            status=status,
        )
    except Exception:
        LOGGER.exception("Processor stopped after a failure")
        raise
    finally:
        status.set_ready(False)
        monitor.shutdown()
        monitor.server_close()


if __name__ == "__main__":
    main()
