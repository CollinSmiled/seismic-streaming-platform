import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from confluent_kafka import KafkaError, Message

from seismic_stream.events import EarthquakeEvent
from seismic_stream.ingestion import fixture_producer

CAPTURE = Path(__file__).parent / "fixtures" / "emsc_catalogue_capture.json"
INGESTED_AT = datetime(2026, 10, 3, 17, 0, tzinfo=UTC)


class FakeProducer:
    def __init__(self, error: KafkaError | None = None, remaining: int = 0) -> None:
        self.records: list[tuple[str, bytes, bytes]] = []
        self.callbacks: list[Callable[[KafkaError | None, Message], None]] = []
        self.error = error
        self.remaining = remaining

    def produce(
        self,
        *,
        topic: str,
        key: bytes,
        value: bytes,
        on_delivery: Callable[[KafkaError | None, Message], None],
    ) -> None:
        self.records.append((topic, key, value))
        self.callbacks.append(on_delivery)

    def flush(self, _timeout: float) -> int:
        if self.remaining:
            return self.remaining
        for callback in self.callbacks:
            callback(self.error, cast(Message, None))
        return 0


def test_fixture_publishes_emsc_keys_and_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeProducer()
    monkeypatch.setattr(fixture_producer, "Producer", lambda _: fake)
    events = fixture_producer.load_fixture(CAPTURE, ingested_at=INGESTED_AT)

    assert fixture_producer.publish_events(events, bootstrap_servers="unused") == 2
    assert [record[1] for record in fake.records] == [
        b"20261003_0000205",
        b"20261003_0000204",
    ]
    assert all(record[0] == "earthquake.events.v1" for record in fake.records)
    assert [
        EarthquakeEvent.from_wire_bytes(record[2]) for record in fake.records
    ] == events


@pytest.mark.parametrize(
    ("error", "remaining", "expected"),
    [
        (KafkaError(KafkaError._MSG_TIMED_OUT), 0, RuntimeError),
        (None, 1, TimeoutError),
    ],
)
def test_delivery_failure_is_not_reported_as_success(
    monkeypatch: pytest.MonkeyPatch,
    error: KafkaError | None,
    remaining: int,
    expected: type[Exception],
) -> None:
    fake = FakeProducer(error, remaining)
    monkeypatch.setattr(fixture_producer, "Producer", lambda _: fake)
    events = fixture_producer.load_fixture(CAPTURE, ingested_at=INGESTED_AT)

    with pytest.raises(expected):
        fixture_producer.publish_events(events, bootstrap_servers="unused")


def test_fixture_must_be_bounded_feature_collection(tmp_path: Path) -> None:
    bad_fixture = tmp_path / "invalid.json"
    bad_fixture.write_text(json.dumps({"type": "FeatureCollection", "features": []}))

    with pytest.raises(ValueError, match="1 to 100"):
        fixture_producer.load_fixture(bad_fixture, ingested_at=INGESTED_AT)

    oversized: dict[str, Any] = {"type": "FeatureCollection", "features": [{}]}
    oversized["padding"] = "x" * (fixture_producer.MAX_FIXTURE_BYTES + 1)
    bad_fixture.write_text(json.dumps(oversized))
    with pytest.raises(ValueError, match="size limit"):
        fixture_producer.load_fixture(bad_fixture, ingested_at=INGESTED_AT)
