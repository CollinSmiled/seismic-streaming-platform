"""FDSN overlap, bounds, and checkpoint advancement rules."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from seismic_stream.events import EarthquakeEvent
from seismic_stream.ingestion.reconcile import (
    OVERLAP,
    ReconciliationError,
    fetch_features,
    reconcile_once,
)

CAPTURE = Path(__file__).parent / "fixtures" / "emsc_catalogue_capture.json"
FEATURES = json.loads(CAPTURE.read_text(encoding="utf-8"))["features"]
NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


class MemoryCheckpoint:
    def __init__(self, scanned_at: datetime | None = None) -> None:
        self.scanned_at = scanned_at
        self.saves = 0

    def load(self) -> datetime | None:
        return self.scanned_at

    def save(self, scanned_at: datetime) -> None:
        self.scanned_at = scanned_at
        self.saves += 1


def catalogue_client(
    features: list[object], requests: list[httpx.Request]
) -> httpx.Client:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, json={"type": "FeatureCollection", "features": features}
        )

    return httpx.Client(transport=httpx.MockTransport(respond))


def test_overlap_republishes_missed_event_and_advances_after_ack() -> None:
    checkpoint = MemoryCheckpoint(NOW - timedelta(minutes=20))
    requests: list[httpx.Request] = []
    published: list[EarthquakeEvent] = []
    with catalogue_client([FEATURES[0]], requests) as client:
        assert reconcile_once(checkpoint, client, published.append, now=NOW) == 1
        assert (
            reconcile_once(
                checkpoint, client, published.append, now=NOW + timedelta(minutes=1)
            )
            == 1
        )

    assert [event.event_id for event in published] == [
        "20261003_0000205",
        "20261003_0000205",
    ]
    assert published[0].source_action is None
    assert requests[0].url.params["updatedafter"] == (
        NOW - timedelta(minutes=20) - OVERLAP
    ).strftime("%Y-%m-%dT%H:%M:%S.%f")
    assert requests[1].url.params["updatedafter"] == (NOW - OVERLAP).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )
    assert requests[0].url.params["format"] == "json"
    assert requests[0].url.params["catalog"] == "EMSC-RTS"
    assert checkpoint.scanned_at == NOW + timedelta(minutes=1)
    assert checkpoint.saves == 2


def test_failed_publish_and_bad_feature_keep_checkpoint() -> None:
    checkpoint = MemoryCheckpoint(NOW - timedelta(minutes=20))

    def fail(_event: EarthquakeEvent) -> None:
        raise RuntimeError("Kafka is unavailable")

    with (
        catalogue_client([FEATURES[0]], []) as client,
        pytest.raises(RuntimeError, match="Kafka"),
    ):
        reconcile_once(checkpoint, client, fail, now=NOW)
    assert checkpoint.saves == 0

    with (
        catalogue_client([{"type": "Feature", "properties": {}}], []) as client,
        pytest.raises(ReconciliationError, match="invalid event"),
    ):
        reconcile_once(checkpoint, client, lambda _: None, now=NOW)
    assert checkpoint.saves == 0


def test_empty_and_oversized_result_handling() -> None:
    checkpoint = MemoryCheckpoint()
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(204))
    ) as client:
        assert reconcile_once(checkpoint, client, lambda _: None, now=NOW) == 0
    assert checkpoint.scanned_at == NOW

    requests: list[httpx.Request] = []
    with (
        catalogue_client(FEATURES, requests) as client,
        pytest.raises(ReconciliationError, match="max_events"),
    ):
        reconcile_once(checkpoint, client, lambda _: None, now=NOW, max_events=1)
    assert requests[0].url.params["limit"] == "2"
    assert checkpoint.saves == 1


def test_http_error_keeps_checkpoint() -> None:
    checkpoint = MemoryCheckpoint(NOW)
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(503))
        ) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        reconcile_once(checkpoint, client, lambda _: None, now=NOW)
    assert checkpoint.saves == 0


def test_fetch_rejects_invalid_limit() -> None:
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(204))
        ) as client,
        pytest.raises(ValueError, match="max_events"),
    ):
        fetch_features(
            client,
            url="https://example.invalid",
            updated_after=NOW,
            max_events=20000,
        )
