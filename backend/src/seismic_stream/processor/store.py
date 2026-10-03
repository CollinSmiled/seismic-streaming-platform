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
            return result.rowcount > 0
