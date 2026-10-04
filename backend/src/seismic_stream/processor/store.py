"""PostgreSQL current-event projection."""

import hashlib
import json

from psycopg_pool import ConnectionPool

from seismic_stream.events import EarthquakeEvent


def content_fingerprint(event: EarthquakeEvent) -> str:
    """Hash source content, excluding when and how we observed it."""
    source_fields = event.model_dump(
        mode="json", exclude={"ingested_at", "source_action"}
    )
    canonical = json.dumps(source_fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EventStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def write(self, event: EarthquakeEvent) -> bool:
        """Commit a newer revision; return False for duplicates or stale records."""
        with self.pool.connection() as connection, connection.transaction():
            clock = connection.execute(
                "SELECT last_cursor FROM earthquake_change_clock WHERE id = 1 FOR UPDATE"
            ).fetchone()
            if clock is None:
                raise RuntimeError("earthquake change clock is missing")
            existed = (
                connection.execute(
                    "SELECT 1 FROM earthquake_events WHERE event_id = %s",
                    (event.event_id,),
                ).fetchone()
                is not None
            )
            result = connection.execute(
                """INSERT INTO earthquake_events (
                           event_id, source, source_action, event_time,
                           source_updated_at, ingested_at, latitude, longitude,
                           depth_km, magnitude, magnitude_type, region,
                           source_catalog, content_sha256
                       ) VALUES (
                           %(event_id)s, %(source)s, %(source_action)s, %(event_time)s,
                           %(source_updated_at)s, %(ingested_at)s, %(latitude)s,
                           %(longitude)s, %(depth_km)s, %(magnitude)s,
                           %(magnitude_type)s, %(region)s, %(source_catalog)s,
                           %(content_sha256)s
                       ) ON CONFLICT (event_id) DO UPDATE SET
                           source_action = EXCLUDED.source_action,
                           event_time = EXCLUDED.event_time,
                           source_updated_at = EXCLUDED.source_updated_at,
                           ingested_at = EXCLUDED.ingested_at,
                           latitude = EXCLUDED.latitude,
                           longitude = EXCLUDED.longitude,
                           depth_km = EXCLUDED.depth_km,
                           magnitude = EXCLUDED.magnitude,
                           magnitude_type = EXCLUDED.magnitude_type,
                           region = EXCLUDED.region,
                           source_catalog = EXCLUDED.source_catalog,
                           content_sha256 = EXCLUDED.content_sha256,
                           persisted_at = now()
                       WHERE
                           (EXCLUDED.source_updated_at IS NOT NULL
                            AND earthquake_events.source_updated_at IS NULL)
                           OR (EXCLUDED.source_updated_at > earthquake_events.source_updated_at)
                           OR (EXCLUDED.source_updated_at IS NOT DISTINCT FROM
                               earthquake_events.source_updated_at
                               AND EXCLUDED.content_sha256 > earthquake_events.content_sha256)""",
                {
                    **event.model_dump(),
                    "content_sha256": content_fingerprint(event),
                },
            )
            if result.rowcount == 0:
                return False
            cursor = clock[0] + 1
            connection.execute(
                "UPDATE earthquake_change_clock SET last_cursor = %s WHERE id = 1",
                (cursor,),
            )
            if existed:
                connection.execute(
                    "UPDATE earthquake_events SET change_cursor = %s WHERE event_id = %s",
                    (cursor, event.event_id),
                )
            else:
                connection.execute(
                    """UPDATE earthquake_events
                       SET change_cursor = %s, created_cursor = %s
                       WHERE event_id = %s""",
                    (cursor, cursor, event.event_id),
                )
            connection.execute(
                "SELECT pg_notify('earthquake_changes', %s)", (str(cursor),)
            )
            return True
