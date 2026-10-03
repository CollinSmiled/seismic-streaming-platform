"""Normalize EMSC catalogue features and WebSocket notifications."""

import json
from datetime import datetime
from typing import Any, Literal, cast

from seismic_stream.events import EarthquakeEvent

MAX_SOURCE_MESSAGE_BYTES = 64 * 1024


class SourceMessageError(ValueError):
    """The upstream envelope is missing or malformed."""


def parse_emsc_notification(
    raw_message: str | bytes, *, ingested_at: datetime
) -> EarthquakeEvent:
    encoded = (
        raw_message.encode("utf-8") if isinstance(raw_message, str) else raw_message
    )
    if len(encoded) > MAX_SOURCE_MESSAGE_BYTES:
        raise SourceMessageError("EMSC notification exceeds the size limit")
    try:
        message = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceMessageError("EMSC notification is not valid JSON") from error
    if not isinstance(message, dict):
        raise SourceMessageError("EMSC notification must be an object")
    if message.get("action") not in ("create", "update"):
        raise SourceMessageError("unsupported EMSC notification action")
    return parse_emsc_feature(
        message.get("data"),
        ingested_at=ingested_at,
        source_action=cast(Literal["create", "update"], message["action"]),
    )


def parse_emsc_feature(
    feature: Any,
    *,
    ingested_at: datetime,
    source_action: Literal["create", "update"] | None = None,
) -> EarthquakeEvent:
    """Map EMSC properties, never GeoJSON's negated depth coordinate."""
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise SourceMessageError("EMSC data must be a GeoJSON Feature")
    properties = feature.get("properties")
    if not isinstance(properties, dict):
        raise SourceMessageError("EMSC feature must contain properties")
    required = ("unid", "time", "lat", "lon")
    if any(name not in properties for name in required):
        raise SourceMessageError("EMSC feature is missing a required property")
    return EarthquakeEvent(
        event_id=properties["unid"],
        source_action=source_action,
        event_time=properties["time"],
        source_updated_at=properties.get("lastupdate"),
        ingested_at=ingested_at,
        latitude=properties["lat"],
        longitude=properties["lon"],
        depth_km=properties.get("depth"),
        magnitude=properties.get("mag"),
        magnitude_type=properties.get("magtype"),
        region=properties.get("flynn_region"),
        source_catalog=properties.get("source_catalog"),
    )
