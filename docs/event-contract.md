# Earthquake event contract, version 1

Kafka topic: `earthquake.events.v1`. Message key: the EMSC `unid` encoded as UTF-8. Message value: UTF-8 JSON with `schema_version: 1`. A consumer rejects unsupported versions and unknown contract fields. A source update retains the same key so Kafka keeps its revisions ordered within a partition.

| Field | Type | EMSC field or rule |
| --- | --- | --- |
| `schema_version` | integer | Fixed `1` |
| `source` | string | Fixed `EMSC` (the portal, not necessarily the event author) |
| `event_id` | string | `properties.unid`, 1–128 characters without whitespace |
| `source_action` | `create`, `update`, or null | WebSocket action; null for catalogue reconciliation |
| `event_time` | UTC timestamp | `properties.time`, earthquake origin time |
| `source_updated_at` | UTC timestamp or null | `properties.lastupdate` |
| `ingested_at` | UTC timestamp | Time our ingestion observed the record |
| `latitude`, `longitude` | finite numbers | `properties.lat`, `properties.lon`; ranges ±90, ±180 |
| `depth_km`, `magnitude` | finite numbers or null | `properties.depth`, `properties.mag` |
| `magnitude_type`, `region`, `source_catalog` | strings or null | `magtype`, `flynn_region`, `source_catalog` |

Required values are the ID, origin time, coordinates, and ingestion time. Optional source fields remain null when absent. Numeric strings, nonfinite numbers, naive timestamps, invalid actions, and oversized messages are rejected. The normalized wire value is capped at 16 KiB; an upstream WebSocket message is capped at 64 KiB. `properties.depth` is used for kilometers below the surface; the GeoJSON geometry's third coordinate is negative for the captured features and is not used as depth.

The fixture in `backend/tests/fixtures/emsc_catalogue_capture.json` is a frozen two-event response from EMSC's FDSN event endpoint, captured on 2026-10-03. The WebSocket envelope test wraps one captured feature in the `{"action": ..., "data": ...}` shape shown by [EMSC's real-time documentation](https://www.seismicportal.eu/realtime.html). Live WebSocket behavior will be checked when ingestion connects to it in a later increment. EMSC's [FDSN documentation](https://www.seismicportal.eu/fdsn-wsevent.html) describes the catalogue source.
