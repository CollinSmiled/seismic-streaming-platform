"""Exercise a source notification, recovery scan, Kafka, projection, and API."""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from confluent_kafka import OFFSET_INVALID, Consumer, Message, TopicPartition
from confluent_kafka.admin import AdminClient, NewTopic  # type: ignore[attr-defined]
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg_pool import ConnectionPool
from websockets.sync.server import ServerConnection, serve

from seismic_stream.api.app import create_app
from seismic_stream.events import EarthquakeEvent
from seismic_stream.ingestion.live import ingest_connection
from seismic_stream.ingestion.publisher import KafkaEventPublisher
from seismic_stream.ingestion.reconcile import reconcile_once
from seismic_stream.processor.store import EventStore
from seismic_stream.processor.worker import process_record
from tests.kafka_support import watermarks_when_ready

CAPTURE = Path(__file__).parent / "fixtures" / "emsc_catalogue_capture.json"
FEATURES = json.loads(CAPTURE.read_text(encoding="utf-8"))["features"]
SCAN_TIME = datetime(2026, 10, 3, 17, tzinfo=UTC)


class FailOnceStore(EventStore):
    def __init__(self, pool: ConnectionPool) -> None:
        super().__init__(pool)
        self.fail_next = True

    def write(self, event: EarthquakeEvent) -> bool:
        if self.fail_next:
            self.fail_next = False
            raise psycopg.OperationalError("injected database write failure")
        return super().write(event)


class MemoryCheckpoint:
    def __init__(self) -> None:
        self.scanned_at: datetime | None = None

    def load(self) -> datetime | None:
        return self.scanned_at

    def save(self, scanned_at: datetime) -> None:
        self.scanned_at = scanned_at


@contextmanager
def local_feed(feature: object, *, action: str) -> Iterator[str]:
    notification = json.dumps({"action": action, "data": feature})

    def handler(connection: ServerConnection) -> None:
        connection.send(notification)

    with serve(handler, "127.0.0.1", 0) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"ws://127.0.0.1:{server.socket.getsockname()[1]}"
        finally:
            server.shutdown()
            thread.join(timeout=5)


def next_record(consumer: Consumer) -> Message:
    record = consumer.poll(10)
    assert record is not None and record.error() is None
    return record


@pytest.mark.integration
def test_websocket_failure_replay_revision_and_fdsn_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = os.getenv("DATABASE_URL")
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if not base_url or not bootstrap:
        pytest.skip("set DATABASE_URL and KAFKA_BOOTSTRAP_SERVERS")

    topic = f"earthquake.events.v1.e2e-{uuid4().hex}"
    database_name = f"seismic_e2e_{uuid4().hex}"
    test_url = urlunsplit(urlsplit(base_url)._replace(path=f"/{database_name}"))
    admin = AdminClient({"bootstrap.servers": bootstrap})
    admin.create_topics([NewTopic(topic, 1, 1)])[topic].result(timeout=15)
    try:
        with psycopg.connect(base_url, autocommit=True) as database_admin:
            database_admin.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
            )
            try:
                monkeypatch.setenv("DATABASE_URL", test_url)
                command.upgrade(
                    Config(str(Path(__file__).parents[1] / "alembic.ini")), "head"
                )
                consumer = Consumer(
                    {
                        "bootstrap.servers": bootstrap,
                        "group.id": f"seismic-e2e-{uuid4().hex}",
                        "enable.auto.commit": False,
                    }
                )
                publisher = KafkaEventPublisher(bootstrap, topic=topic)
                try:
                    partition = TopicPartition(topic, 0)
                    _, high = watermarks_when_ready(consumer, partition)
                    consumer.assign([TopicPartition(topic, 0, high)])
                    with ConnectionPool(test_url, min_size=1, max_size=2) as pool:
                        store = FailOnceStore(pool)
                        with TestClient(create_app(pool)) as api:
                            with local_feed(FEATURES[0], action="create") as url:
                                assert ingest_connection(url, publisher.publish) == 1
                            first = next_record(consumer)
                            assert first.key() == b"20261003_0000205"

                            with pytest.raises(
                                psycopg.OperationalError, match="injected"
                            ):
                                process_record(first, store=store, consumer=consumer)
                            assert (
                                consumer.committed([partition], timeout=10)[0].offset
                                == OFFSET_INVALID
                            )
                            assert api.get("/api/v1/earthquakes").json()["items"] == []

                            process_record(first, store=store, consumer=consumer)
                            assert (
                                consumer.committed([partition], timeout=10)[0].offset
                                == high + 1
                            )
                            initial = api.get("/api/v1/earthquakes").json()
                            assert [item["event_id"] for item in initial["items"]] == [
                                "20261003_0000205"
                            ]
                            assert initial["latest_change_cursor"] == 1

                            revised = json.loads(json.dumps(FEATURES[0]))
                            revised["properties"]["lastupdate"] = (
                                "2026-10-03T16:56:45.265185Z"
                            )
                            revised["properties"]["mag"] = 2.4
                            with local_feed(revised, action="update") as url:
                                assert ingest_connection(url, publisher.publish) == 1
                            process_record(
                                next_record(consumer), store=store, consumer=consumer
                            )
                            detail = api.get(
                                "/api/v1/earthquakes/20261003_0000205"
                            ).json()
                            assert detail["magnitude"] == 2.4
                            assert detail["source_action"] == "update"
                            changes = api.get(
                                "/api/v1/earthquakes/changes", params={"after": 1}
                            ).json()["items"]
                            assert [item["kind"] for item in changes] == ["updated"]

                            def catalogue(_request: httpx.Request) -> httpx.Response:
                                return httpx.Response(
                                    200,
                                    json={
                                        "type": "FeatureCollection",
                                        "features": [FEATURES[1]],
                                    },
                                )

                            checkpoint = MemoryCheckpoint()
                            with httpx.Client(
                                transport=httpx.MockTransport(catalogue)
                            ) as client:
                                assert (
                                    reconcile_once(
                                        checkpoint,
                                        client,
                                        publisher.publish,
                                        now=SCAN_TIME,
                                    )
                                    == 1
                                )
                                process_record(
                                    next_record(consumer),
                                    store=store,
                                    consumer=consumer,
                                )
                                assert checkpoint.scanned_at == SCAN_TIME
                                assert (
                                    reconcile_once(
                                        checkpoint,
                                        client,
                                        publisher.publish,
                                        now=SCAN_TIME,
                                    )
                                    == 1
                                )
                                process_record(
                                    next_record(consumer),
                                    store=store,
                                    consumer=consumer,
                                )

                            final = api.get("/api/v1/earthquakes").json()
                            assert [item["event_id"] for item in final["items"]] == [
                                "20261003_0000205",
                                "20261003_0000204",
                            ]
                            assert final["latest_change_cursor"] == 3
                            assert api.get("/ready").status_code == 200
                            with pool.connection() as connection:
                                assert connection.execute(
                                    "SELECT count(*) FROM earthquake_events"
                                ).fetchone() == (2,)
                            assert (
                                consumer.committed([partition], timeout=10)[0].offset
                                == high + 4
                            )
                finally:
                    consumer.close()
                    publisher.close()
            finally:
                database_admin.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
    finally:
        admin.delete_topics([topic])[topic].result(timeout=15)
