"""Contract tests against a frozen EMSC catalogue response."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from seismic_stream.events import MAX_EVENT_BYTES, EarthquakeEvent
from seismic_stream.ingestion.emsc import (
    MAX_SOURCE_MESSAGE_BYTES,
    SourceMessageError,
    parse_emsc_feature,
    parse_emsc_notification,
)

CAPTURE = Path(__file__).parent / "fixtures" / "emsc_catalogue_capture.json"
INGESTED_AT = datetime(2026, 10, 3, 17, 0, tzinfo=UTC)


def captured_features() -> list[dict[str, Any]]:
    data: dict[str, Any] = json.loads(CAPTURE.read_text(encoding="utf-8"))
    return cast(list[dict[str, Any]], data["features"])


def notification(feature: dict[str, Any], action: str = "create") -> bytes:
    return json.dumps({"action": action, "data": feature}).encode("utf-8")


def test_captured_catalogue_fields_and_depth() -> None:
    first, second = (
        parse_emsc_feature(feature, ingested_at=INGESTED_AT)
        for feature in captured_features()
    )

    assert first.event_id == "20261003_0000205"
    assert first.depth_km == 31.9
    assert first.latitude == 36.6067
    assert first.longitude == -7.6317
    assert first.source_updated_at == datetime(
        2026, 10, 3, 16, 55, 45, 265185, tzinfo=UTC
    )
    assert first.source_action is None
    assert second.depth_km == 9.2
    assert second.region == "SWITZERLAND"


def test_documented_websocket_envelope_maps_to_same_contract() -> None:
    event = parse_emsc_notification(
        notification(captured_features()[0], "update"), ingested_at=INGESTED_AT
    )

    assert event.event_id == "20261003_0000205"
    assert event.source_action == "update"
    assert event.source == "EMSC"
    assert event.schema_version == 1
    assert EarthquakeEvent.from_wire_bytes(event.to_wire_bytes()) == event


def test_missing_optional_properties_remain_null() -> None:
    feature = captured_features()[0]
    for name in ("lastupdate", "depth", "mag", "magtype", "flynn_region"):
        del feature["properties"][name]

    event = parse_emsc_feature(feature, ingested_at=INGESTED_AT)

    assert event.source_updated_at is None
    assert event.depth_km is None
    assert event.magnitude is None
    assert event.magnitude_type is None
    assert event.region is None


@pytest.mark.parametrize("missing", ["unid", "time", "lat", "lon"])
def test_missing_required_property_is_rejected(missing: str) -> None:
    feature = captured_features()[0]
    del feature["properties"][missing]

    with pytest.raises(SourceMessageError, match="missing a required property"):
        parse_emsc_feature(feature, ingested_at=INGESTED_AT)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("lat", 91.0),
        ("lon", -181.0),
        ("lat", "36.6"),
        ("depth", float("nan")),
        ("mag", float("inf")),
        ("time", "2026-10-03T16:48:06"),
        ("unid", "bad id"),
    ],
)
def test_malformed_field_is_rejected(field: str, value: object) -> None:
    feature = captured_features()[0]
    feature["properties"][field] = value

    with pytest.raises(ValidationError):
        parse_emsc_feature(feature, ingested_at=INGESTED_AT)


def test_unsupported_action_and_malformed_json_are_rejected() -> None:
    with pytest.raises(SourceMessageError, match="unsupported"):
        parse_emsc_notification(
            notification(captured_features()[0], "delete"), ingested_at=INGESTED_AT
        )
    with pytest.raises(SourceMessageError, match="valid JSON"):
        parse_emsc_notification(b"{broken", ingested_at=INGESTED_AT)


def test_input_and_wire_size_limits() -> None:
    with pytest.raises(SourceMessageError, match="size limit"):
        parse_emsc_notification(
            b" " * (MAX_SOURCE_MESSAGE_BYTES + 1), ingested_at=INGESTED_AT
        )
    with pytest.raises(ValueError, match="size limit"):
        EarthquakeEvent.from_wire_bytes(b" " * (MAX_EVENT_BYTES + 1))


def test_unsupported_schema_version_is_rejected() -> None:
    event = parse_emsc_feature(captured_features()[0], ingested_at=INGESTED_AT)
    payload = json.loads(event.to_wire_bytes())
    payload["schema_version"] = 2

    with pytest.raises(ValidationError):
        EarthquakeEvent.from_wire_bytes(json.dumps(payload).encode("utf-8"))
