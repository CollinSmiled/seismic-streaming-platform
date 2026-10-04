"""Drive the EMSC reader with a local WebSocket; Kafka remains optional."""

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Thread, Timer
from uuid import uuid4

import pytest
from confluent_kafka import Consumer, KafkaError, KafkaException, TopicPartition
from confluent_kafka.admin import AdminClient, NewTopic  # type: ignore[attr-defined]
from websockets.sync.server import ServerConnection, serve

from seismic_stream.events import EarthquakeEvent
from seismic_stream.ingestion.live import ingest_connection, ingest_forever
from seismic_stream.ingestion.publisher import KafkaDeliveryError, KafkaEventPublisher

CAPTURE = Path(__file__).parent / "fixtures" / "emsc_catalogue_capture.json"
TOPIC = "earthquake.events.v1.live-test"


def notification(action: str = "create", index: int = 0) -> str:
    feature = json.loads(CAPTURE.read_text(encoding="utf-8"))["features"][index]
    return json.dumps({"action": action, "data": feature})


@contextmanager
def local_feed(
    messages: list[str],
    *,
    one_per_connection: bool = False,
    idle_until: Event | None = None,
) -> Iterator[str]:
    connections = [0]

    def handler(connection: ServerConnection) -> None:
        index = connections[0]
        connections[0] += 1
        selected = [messages[index % len(messages)]] if one_per_connection else messages
        for message in selected:
            connection.send(message)
        if idle_until is not None:
            idle_until.wait(2)

    with serve(handler, "127.0.0.1", 0) as server:
        port = server.socket.getsockname()[1]
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"ws://127.0.0.1:{port}"
        finally:
            server.shutdown()
            thread.join(timeout=5)


def test_local_websocket_uses_shared_contract_and_skips_bad_message() -> None:
    published: list[EarthquakeEvent] = []
    with local_feed(["{broken", notification("update")]) as url:
        ingest_connection(url, published.append)

    assert len(published) == 1
    assert published[0].event_id == "20261003_0000205"
    assert published[0].source_action == "update"
    assert published[0].schema_version == 1
    assert published[0].ingested_at.tzinfo is not None


def test_disconnect_reconnects_and_continues_reading() -> None:
    stop = Event()
    published: list[EarthquakeEvent] = []

    def publish(event: EarthquakeEvent) -> None:
        published.append(event)
        if len(published) == 2:
            stop.set()

    with local_feed(
        [notification(index=0), notification(index=1)], one_per_connection=True
    ) as url:
        watchdog = Timer(5, stop.set)
        watchdog.start()
        try:
            ingest_forever(
                url,
                publish,
                stop=stop,
                retry_min_seconds=0.01,
                retry_max_seconds=0.05,
            )
        finally:
            watchdog.cancel()

    assert [event.event_id for event in published] == [
        "20261003_0000205",
        "20261003_0000204",
    ]


def test_kafka_outage_reconnects_without_unbounded_queue() -> None:
    stop = Event()
    attempts = 0

    def publish(_event: EarthquakeEvent) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise KafkaDeliveryError("simulated broker outage")
        stop.set()

    with local_feed([notification()]) as url:
        watchdog = Timer(5, stop.set)
        watchdog.start()
        try:
            ingest_forever(
                url,
                publish,
                stop=stop,
                retry_min_seconds=0.01,
                retry_max_seconds=0.05,
            )
        finally:
            watchdog.cancel()
    assert attempts == 2


def test_shutdown_ends_an_idle_connection() -> None:
    stop = Event()
    with local_feed([], idle_until=stop) as url:
        timer = Timer(0.1, stop.set)
        timer.start()
        try:
            assert ingest_connection(url, lambda _: None, stop=stop) == 0
        finally:
            timer.cancel()


@pytest.mark.integration
def test_websocket_event_is_acknowledged_and_read_from_kafka() -> None:
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if not bootstrap:
        pytest.skip("set KAFKA_BOOTSTRAP_SERVERS to run Kafka integration tests")

    admin = AdminClient({"bootstrap.servers": bootstrap})
    try:
        admin.create_topics([NewTopic(TOPIC, 1, 1)])[TOPIC].result(timeout=15)
    except KafkaException as error:
        if error.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
            raise

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": f"seismic-live-test-{uuid4().hex}",
            "enable.auto.commit": False,
        }
    )
    try:
        partition = TopicPartition(TOPIC, 0)
        _, high = consumer.get_watermark_offsets(partition, timeout=15)
        consumer.assign([TopicPartition(TOPIC, 0, high)])
        publisher = KafkaEventPublisher(bootstrap, topic=TOPIC)
        try:
            with local_feed([notification()]) as url:
                ingest_connection(url, publisher.publish)
        finally:
            publisher.close()
        deadline = time.monotonic() + 15
        record = None
        while record is None and time.monotonic() < deadline:
            record = consumer.poll(1)
        assert record is not None and record.error() is None
        assert record.key() == b"20261003_0000205"
        payload = record.value()
        assert payload is not None
        assert EarthquakeEvent.from_wire_bytes(payload).schema_version == 1
    finally:
        consumer.close()
