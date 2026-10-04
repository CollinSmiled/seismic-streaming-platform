# Earthquake API

Run the API with `DATABASE_URL` pointing at a migrated PostgreSQL database. All times use ISO 8601 with a UTC offset. The browser sends requests to `/api` through the Vite development proxy.

## List events

`GET /api/v1/earthquakes`

| Parameter | Meaning |
| --- | --- |
| `limit` | Page size, 1–200; default 100. |
| `cursor` | Opaque `next_cursor` from the previous page. |
| `start_time`, `end_time` | Inclusive event-time range. |
| `min_lon`, `min_lat`, `max_lon`, `max_lat` | Optional map bounds; supply all four. A longitude range crossing 180° uses `min_lon > max_lon`. |

Events sort newest first by `(event_time, event_id)`. A page contains `items`, `next_cursor` (null when there are no more rows), and `latest_change_cursor`. The cursor is the committed change position of the same database snapshot as the listed events. For example:

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
  "next_cursor": null,
  "latest_change_cursor": 12
}
```

The cursor is a position in the current-event table, not a snapshot. New events may appear before that position while a user pages. The page limit bounds one response; the UI loads further pages only when requested. The API does not filter by magnitude yet.

## Single event

`GET /api/v1/earthquakes/{event_id}` returns the same event shape. Unknown IDs return 404. Invalid parameters return 422. If the database is not configured or is unavailable, the API returns 503. Errors use `{"error":{"code":"...","message":"..."}}`.

## Changes and live updates

`GET /api/v1/earthquakes/changes?after=12&limit=100` returns current events whose latest committed change cursor is greater than `after`, ordered by cursor. `after` is a nonnegative integer; `limit` is 1–200. Each item has `cursor`, `kind` (`created` or `updated`), and `event` with the same shape as the historical API. `next_cursor` is the last returned cursor when another page is available. Continue until `next_cursor` is null.

`GET /api/v1/earthquakes/stream?after=12` is an SSE stream. Each `earthquake` event has an integer `id` and JSON `data` matching a change item. Reconnect using the highest cursor processed, then call `/changes` for catch-up. The stream itself also replays changes after `after`, so duplicate delivery is expected and clients should deduplicate by event ID and cursor. The browser shows a notice only when it sees a new event, and a revision updates the existing marker.

The change feed is a **current-state projection**, not an audit log. If one earthquake changes repeatedly while a client is away, catch-up returns only its latest revision. The `kind` field is `created` if that earthquake was first committed after the requested cursor. PostgreSQL notifications wake live readers after commit; the cursor query remains the source of truth when notifications are missed. On Windows' default event loop, SSE checks the cursor every two seconds because Psycopg async LISTEN requires a selector loop. Other supported runtimes use LISTEN. Older revisions and deletes are not represented yet.
