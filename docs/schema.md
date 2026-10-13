# Storage schema

Migrations live in `backend/migrations/versions` and are applied in order with `alembic upgrade head`. PostgreSQL holds a current earthquake projection, a serialized change position, and an EMSC catalogue checkpoint. Kafka retains the input event stream and the quarantine stream.

## `earthquake_events`

`event_id` is the EMSC `unid` and the primary key. Each ID has one **current** row. `source` is constrained to `EMSC`; `source_action` is nullable because FDSN catalogue entries have no WebSocket action. `event_time`, coordinates, and `ingested_at` are required. Depth, magnitude, magnitude type, region, source catalogue, and `source_updated_at` can be null when upstream data is absent. Latitude and longitude have range checks; magnitude, depth, and coordinates must be finite. `content_sha256` is the hash of normalized source content, excluding local observation time and action. `persisted_at` records the latest accepted database write.

The table has an `event_time` index for historical pages and a `change_cursor` index for live catch-up. `created_cursor` records when the ID first entered the projection; `change_cursor` records its latest accepted change. A replay or older revision does not change either cursor. The row does not preserve older revisions or deletes.

## `earthquake_change_clock`

This table has one row (`id = 1`) with `last_cursor`. A writer locks the row, accepts a newer event revision, increments the cursor, updates the event row, and issues `pg_notify` in one transaction. PostgreSQL releases the notification only after commit. The API reads the cursor and event page from a repeatable-read snapshot, so a client can start catch-up from the position corresponding to its initial page.

## `source_reconciliation_checkpoints`

`source` is the primary key; the current worker uses `EMSC`. `scanned_at` is the start time of the last fully acknowledged FDSN scan. `committed_at` records when that checkpoint was stored. The worker uses a PostgreSQL advisory lock so only one EMSC reconciliation scan runs at once. A failed scan leaves `scanned_at` unchanged, allowing replay on the next attempt.

## Kafka records

The input topic is `earthquake.events.v1`, keyed by `event_id`. Its JSON value follows [contract version 1](event-contract.md). The processor commits the source offset after the projection transaction succeeds. Invalid records go to `earthquake.events.v1.quarantine`; its diagnostic value contains source location, failure category, byte count, and hashes, without raw event content. Quarantine acknowledgement precedes the source offset commit. [Persistence notes](persistence.md) explain revision ordering and replay.
