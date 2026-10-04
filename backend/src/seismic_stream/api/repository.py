"""Bounded historical reads from the current earthquake projection."""

import base64
import binascii
import json
import re
from datetime import datetime
from typing import Any, Literal

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict


class EarthquakeRead(BaseModel):
    model_config = ConfigDict(strict=True)

    event_id: str
    source: str
    source_action: str | None
    event_time: datetime
    source_updated_at: datetime | None
    ingested_at: datetime
    latitude: float
    longitude: float
    depth_km: float | None
    magnitude: float | None
    magnitude_type: str | None
    region: str | None
    source_catalog: str | None
    persisted_at: datetime


class EarthquakePage(BaseModel):
    items: list[EarthquakeRead]
    next_cursor: str | None
    latest_change_cursor: int


class EarthquakeChange(BaseModel):
    cursor: int
    kind: Literal["created", "updated"]
    event: EarthquakeRead


class ChangePage(BaseModel):
    items: list[EarthquakeChange]
    next_cursor: int | None


def encode_cursor(event: EarthquakeRead) -> str:
    payload = json.dumps(
        {"event_time": event.event_time.isoformat(), "event_id": event.event_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(value: str) -> tuple[datetime, str]:
    try:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("invalid cursor encoding")
        payload = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        data: Any = json.loads(payload)
        if not isinstance(data, dict) or set(data) != {"event_time", "event_id"}:
            raise ValueError("invalid cursor fields")
        event_time = datetime.fromisoformat(data["event_time"])
        event_id = data["event_id"]
        if event_time.tzinfo is None or event_time.utcoffset() is None:
            raise ValueError("cursor timestamp needs an offset")
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 128:
            raise ValueError("invalid cursor ID")
        if event_id.strip() != event_id or any(char.isspace() for char in event_id):
            raise ValueError("invalid cursor ID")
        return event_time, event_id
    except (
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
        TypeError,
        KeyError,
        ValueError,
    ) as error:
        raise ValueError("invalid pagination cursor") from error


def list_earthquakes(
    pool: ConnectionPool,
    *,
    limit: int,
    cursor: tuple[datetime, str] | None,
    start_time: datetime | None,
    end_time: datetime | None,
    bounds: tuple[float, float, float, float] | None,
) -> EarthquakePage:
    clauses: list[str] = []
    parameters: dict[str, Any] = {"fetch_limit": limit + 1}
    if cursor is not None:
        clauses.append("(event_time, event_id) < (%(cursor_time)s, %(cursor_id)s)")
        parameters["cursor_time"], parameters["cursor_id"] = cursor
    if start_time is not None:
        clauses.append("event_time >= %(start_time)s")
        parameters["start_time"] = start_time
    if end_time is not None:
        clauses.append("event_time <= %(end_time)s")
        parameters["end_time"] = end_time
    if bounds is not None:
        min_lon, min_lat, max_lon, max_lat = bounds
        clauses.append("latitude BETWEEN %(min_lat)s AND %(max_lat)s")
        parameters.update(
            min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat
        )
        if min_lon <= max_lon:
            clauses.append("longitude BETWEEN %(min_lon)s AND %(max_lon)s")
        else:
            clauses.append("(longitude >= %(min_lon)s OR longitude <= %(max_lon)s)")

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    statement = (
        "SELECT event_id, source, source_action, event_time, source_updated_at, "
        "ingested_at, latitude, longitude, depth_km, magnitude, magnitude_type, "
        "region, source_catalog, persisted_at FROM earthquake_events"
        + where
        + " ORDER BY event_time DESC, event_id DESC LIMIT %(fetch_limit)s"
    )
    with pool.connection() as connection, connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        clock = connection.execute(
            "SELECT last_cursor FROM earthquake_change_clock WHERE id = 1"
        ).fetchone()
        if clock is None:
            raise RuntimeError("earthquake change clock is missing")
        with connection.cursor(row_factory=dict_row) as db:
            db.execute(statement, parameters)
            rows = db.fetchall()
    events = [EarthquakeRead.model_validate(row) for row in rows[:limit]]
    next_cursor = encode_cursor(events[-1]) if len(rows) > limit else None
    return EarthquakePage(
        items=events, next_cursor=next_cursor, latest_change_cursor=clock[0]
    )


def list_changes(pool: ConnectionPool, *, after: int, limit: int) -> ChangePage:
    with pool.connection() as connection, connection.cursor(row_factory=dict_row) as db:
        db.execute(
            """SELECT change_cursor, created_cursor, event_id, source, source_action,
                      event_time, source_updated_at, ingested_at, latitude,
                      longitude, depth_km, magnitude, magnitude_type, region,
                      source_catalog, persisted_at
               FROM earthquake_events WHERE change_cursor > %s
               ORDER BY change_cursor ASC LIMIT %s""",
            (after, limit + 1),
        )
        rows = db.fetchall()
    items = [
        EarthquakeChange(
            cursor=row["change_cursor"],
            kind="created" if row["created_cursor"] > after else "updated",
            event=EarthquakeRead.model_validate(
                {
                    key: value
                    for key, value in row.items()
                    if key not in ("change_cursor", "created_cursor")
                }
            ),
        )
        for row in rows[:limit]
    ]
    return ChangePage(
        items=items, next_cursor=items[-1].cursor if len(rows) > limit else None
    )


def get_earthquake(pool: ConnectionPool, event_id: str) -> EarthquakeRead | None:
    with pool.connection() as connection, connection.cursor(row_factory=dict_row) as db:
        db.execute(
            """SELECT event_id, source, source_action, event_time, source_updated_at,
                      ingested_at, latitude, longitude, depth_km, magnitude,
                      magnitude_type, region, source_catalog, persisted_at
               FROM earthquake_events WHERE event_id = %s""",
            (event_id,),
        )
        row = db.fetchone()
    return EarthquakeRead.model_validate(row) if row is not None else None
