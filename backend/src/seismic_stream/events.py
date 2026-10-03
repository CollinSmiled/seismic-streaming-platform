"""Versioned wire contract shared by ingestion and downstream consumers."""

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_EVENT_BYTES = 16 * 1024
TOPIC_NAME = "earthquake.events.v1"


class EarthquakeEvent(BaseModel):
    """One observed EMSC revision, before database revision ordering."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    source: Literal["EMSC"] = "EMSC"
    event_id: str = Field(min_length=1, max_length=128)
    source_action: Literal["create", "update"] | None = None
    event_time: datetime
    source_updated_at: datetime | None = None
    ingested_at: datetime
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    depth_km: float | None = Field(default=None, allow_inf_nan=False)
    magnitude: float | None = Field(default=None, allow_inf_nan=False)
    magnitude_type: str | None = Field(default=None, max_length=32)
    region: str | None = Field(default=None, max_length=255)
    source_catalog: str | None = Field(default=None, max_length=64)

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, value: str) -> str:
        if value.strip() != value or any(character.isspace() for character in value):
            raise ValueError("event_id must not contain whitespace")
        return value

    @field_validator("event_time", "source_updated_at", "ingested_at", mode="before")
    @classmethod
    def require_utc_timestamp(cls, value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, str):
            if "T" not in value:
                raise ValueError("timestamp must use ISO 8601 date-time format")
            try:
                value = datetime.fromisoformat(value)
            except ValueError as error:
                raise ValueError("invalid timestamp") from error
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("timestamp must include a UTC offset")
        if value.utcoffset() is None:
            raise ValueError("timestamp must include a UTC offset")
        return value.astimezone(UTC)

    def to_wire_bytes(self) -> bytes:
        payload = self.model_dump_json().encode("utf-8")
        if len(payload) > MAX_EVENT_BYTES:
            raise ValueError("event exceeds the wire size limit")
        return payload

    @classmethod
    def from_wire_bytes(cls, payload: bytes) -> Self:
        if len(payload) > MAX_EVENT_BYTES:
            raise ValueError("event exceeds the wire size limit")
        return cls.model_validate_json(payload)
