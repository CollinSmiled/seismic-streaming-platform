# Historical earthquake API

Run the API with `DATABASE_URL` pointing at a migrated PostgreSQL database. All times use ISO 8601 with a UTC offset. The browser sends requests to `/api` through the Vite development proxy.

## List events

`GET /api/v1/earthquakes`

| Parameter | Meaning |
| --- | --- |
| `limit` | Page size, 1–200; default 100. |
| `cursor` | Opaque `next_cursor` from the previous page. |
| `start_time`, `end_time` | Inclusive event-time range. |
| `min_lon`, `min_lat`, `max_lon`, `max_lat` | Optional map bounds; supply all four. A longitude range crossing 180° uses `min_lon > max_lon`. |

Events sort newest first by `(event_time, event_id)`. A page contains `items` and `next_cursor`, which is `null` when there are no more rows. For example:

```json
{
  "items": [{
    "event_id": "emsc-123", "source": "EMSC", "source_action": "create",
    "event_time": "2026-10-03T01:00:00Z", "source_updated_at": null,
    "ingested_at": "2026-10-03T01:00:01Z", "latitude": 10.5,
    "longitude": 20.25, "depth_km": 12.4, "magnitude": 5.2,
    "magnitude_type": "Mw", "region": "Test Region", "source_catalog": null,
    "persisted_at": "2026-10-03T01:00:02Z"
  }],
  "next_cursor": null
}
```

The cursor is a position in the current-event table, not a snapshot. New events may appear before that position while a user pages. The page limit bounds one response; the UI loads further pages only when requested. The API does not filter by magnitude yet.

## Single event

`GET /api/v1/earthquakes/{event_id}` returns the same event shape. Unknown IDs return 404. Invalid parameters return 422. If the database is not configured or is unavailable, the API returns 503. Errors use `{"error":{"code":"...","message":"..."}}`.

The API reads the current projection. It does not preserve an event's older revisions, and it does not provide live updates yet.
