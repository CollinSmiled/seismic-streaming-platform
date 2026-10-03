"""Fixture to Kafka to PostgreSQL, including a failed write and replay."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from confluent_kafka import (
    OFFSET_INVALID,
    Consumer,
    KafkaError,
    KafkaException,
    TopicPartition,
)
from confluent_kafka.admin import AdminClient, NewTopic  # type: ignore[attr-defined]
from psycopg import sql
from psycopg_pool import ConnectionPool

from seismic_stream.ingestion.fixture_producer import load_fixture, publish_events
from seismic_stream.processor.store import EventStore, content_fingerprint
from seismic_stream.processor.worker import process_record

TOPIC = "earthquake.events.v1.processor-test"
CAPTURE = Path(__file__).parent / "fixtures" / "emsc_catalogue_capture.json"


@pytest.mark.integration
def test_failed_write_replays_then_fixture_reaches_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("DATABASE_URL")
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if not database_url or not bootstrap:
        pytest.skip("set DATABASE_URL and KAFKA_BOOTSTRAP_SERVERS")

    name = f"seismic_processor_test_{uuid4().hex}"
    test_url = urlunsplit(urlsplit(database_url)._replace(path=f"/{name}"))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    admin = AdminClient({"bootstrap.servers": bootstrap})
    future = admin.create_topics([NewTopic(TOPIC, 1, 1)])[TOPIC]
    try:
        future.result(timeout=15)
    except KafkaException as error:
        if error.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
            raise

    with psycopg.connect(database_url, autocommit=True) as database_admin:
        database_admin.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
        )
        consumer = Consumer(
            {
                "bootstrap.servers": bootstrap,
                "group.id": f"seismic-processor-test-{uuid4().hex}",
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

            first = consumer.poll(10)
            assert first is not None and first.error() is None
            with ConnectionPool(test_url, min_size=1, max_size=1) as pool:
                store = EventStore(pool)
                with pytest.raises(psycopg.errors.UndefinedTable):
                    process_record(first, store=store, consumer=consumer)
                assert (
                    consumer.committed([partition], timeout=10)[0].offset
                    == OFFSET_INVALID
                )

                monkeypatch.setenv("DATABASE_URL", test_url)
                command.upgrade(config, "head")
                process_record(first, store=store, consumer=consumer)
                second = consumer.poll(10)
                assert second is not None and second.error() is None
                process_record(second, store=store, consumer=consumer)

                assert store.write(events[0]) is False
                assert events[0].source_updated_at is not None
                newer = events[0].model_copy(
                    update={
                        "source_updated_at": events[0].source_updated_at
                        + timedelta(seconds=1),
                        "magnitude": 2.4,
                    }
                )
                assert store.write(newer) is True
                assert store.write(events[0]) is False
                assert (
                    store.write(
                        newer.model_copy(update={"ingested_at": datetime.now(UTC)})
                    )
                    is False
                )

                for event_id, revision_time in (
                    ("tie-with-time", events[0].source_updated_at),
                    ("tie-without-time", None),
                ):
                    first_choice = events[0].model_copy(
                        update={
                            "event_id": event_id,
                            "source_updated_at": revision_time,
                        }
                    )
                    second_choice = first_choice.model_copy(update={"magnitude": 3.1})
                    lower, higher = sorted(
                        (first_choice, second_choice), key=content_fingerprint
                    )
                    assert store.write(lower) is True
                    assert store.write(higher) is True
                    assert store.write(lower) is False
                    with psycopg.connect(test_url) as database:
                        stored_magnitude = database.execute(
                            "SELECT magnitude FROM earthquake_events WHERE event_id = %s",
                            (event_id,),
                        ).fetchone()
                    assert stored_magnitude == (higher.magnitude,)

            with psycopg.connect(test_url) as database:
                rows = database.execute(
                    """SELECT event_id, magnitude FROM earthquake_events
                       WHERE event_id LIKE '20261003_%' ORDER BY event_id"""
                ).fetchall()
            assert rows == [
                ("20261003_0000204", 0.9),
                ("20261003_0000205", 2.4),
            ]
            assert consumer.committed([partition], timeout=10)[0].offset == high + 2
        finally:
            consumer.close()
            database_admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
