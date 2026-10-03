from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from confluent_kafka import Consumer, Message

from seismic_stream.ingestion.fixture_producer import load_fixture
from seismic_stream.processor.quarantine import QuarantinePublisher
from seismic_stream.processor.store import EventStore, content_fingerprint
from seismic_stream.processor.worker import process_record

CAPTURE = Path(__file__).parent / "fixtures" / "emsc_catalogue_capture.json"
EVENT = load_fixture(CAPTURE, ingested_at=datetime(2026, 10, 3, 17, 0, tzinfo=UTC))[0]


def mock_record(*, key: bytes | None = None, value: bytes | None = None) -> Mock:
    record = Mock(spec=Message)
    record.key.return_value = key if key is not None else EVENT.event_id.encode()
    record.value.return_value = value if value is not None else EVENT.to_wire_bytes()
    return record


def test_offset_commit_follows_successful_database_write() -> None:
    record = mock_record()
    store = Mock(spec=EventStore)
    consumer = Mock(spec=Consumer)

    process_record(
        cast(Message, record),
        store=cast(EventStore, store),
        consumer=cast(Consumer, consumer),
    )

    store.write.assert_called_once_with(EVENT)
    consumer.commit.assert_called_once_with(message=record, asynchronous=False)


def test_database_failure_does_not_commit_offset() -> None:
    record = mock_record()
    store = Mock(spec=EventStore)
    store.write.side_effect = RuntimeError("database unavailable")
    consumer = Mock(spec=Consumer)

    with pytest.raises(RuntimeError, match="database unavailable"):
        process_record(
            cast(Message, record),
            store=cast(EventStore, store),
            consumer=cast(Consumer, consumer),
        )

    consumer.commit.assert_not_called()


def test_key_mismatch_is_not_written_or_committed() -> None:
    record = mock_record(key=b"another-earthquake")
    store = Mock(spec=EventStore)
    consumer = Mock(spec=Consumer)

    with pytest.raises(ValueError, match="Kafka key"):
        process_record(
            cast(Message, record),
            store=cast(EventStore, store),
            consumer=cast(Consumer, consumer),
        )

    store.write.assert_not_called()
    consumer.commit.assert_not_called()


@pytest.mark.parametrize(
    ("key", "value", "reason"),
    [
        (b"another-earthquake", EVENT.to_wire_bytes(), "key_mismatch"),
        (EVENT.event_id.encode(), b"{bad", "invalid_event"),
        (EVENT.event_id.encode(), None, "missing_value"),
    ],
)
def test_poison_record_is_quarantined_before_offset_commit(
    key: bytes, value: bytes | None, reason: str
) -> None:
    record = mock_record(key=key)
    record.value.return_value = value
    store = Mock(spec=EventStore)
    consumer = Mock(spec=Consumer)
    quarantine = Mock(spec=QuarantinePublisher)
    calls = Mock()
    calls.attach_mock(quarantine.publish, "quarantine")
    calls.attach_mock(consumer.commit, "commit")

    process_record(
        cast(Message, record),
        store=cast(EventStore, store),
        consumer=cast(Consumer, consumer),
        quarantine=cast(QuarantinePublisher, quarantine),
    )

    store.write.assert_not_called()
    assert [call[0] for call in calls.mock_calls] == ["quarantine", "commit"]
    quarantine.publish.assert_called_once_with(record, reason)


def test_failed_quarantine_delivery_does_not_commit_offset() -> None:
    record = mock_record(value=b"{bad")
    store = Mock(spec=EventStore)
    consumer = Mock(spec=Consumer)
    quarantine = Mock(spec=QuarantinePublisher)
    quarantine.publish.side_effect = TimeoutError("Kafka unavailable")

    with pytest.raises(TimeoutError, match="Kafka unavailable"):
        process_record(
            cast(Message, record),
            store=cast(EventStore, store),
            consumer=cast(Consumer, consumer),
            quarantine=cast(QuarantinePublisher, quarantine),
        )

    consumer.commit.assert_not_called()


def test_fingerprint_ignores_local_observation_time_and_action() -> None:
    repeated = EVENT.model_copy(
        update={
            "ingested_at": datetime(2026, 10, 4, tzinfo=UTC),
            "source_action": "update",
        }
    )

    assert content_fingerprint(repeated) == content_fingerprint(EVENT)
