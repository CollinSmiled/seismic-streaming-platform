# PostgreSQL projection and replay

The processor turns the Kafka topic into a **current-event projection**: one PostgreSQL row per EMSC `event_id`. It does not keep every historical revision. The first migration creates `earthquake_events` with database checks for source, valid coordinates, finite depth and magnitude, and the content fingerprint. The origin-time index supports future historical reads.

Run `uv run --frozen alembic upgrade head` from `backend` with `DATABASE_URL` set. The migration test creates an isolated database, applies the migration, checks constraints, rolls back to `base`, and applies it again. A downgrade drops the current-event table and its data; use it only when that loss is intended.

## Revision rule

`source_updated_at` is EMSC's revision timestamp. A record with a newer timestamp replaces the current row. A record with no timestamp ranks below one with a timestamp. For equal timestamps, including two missing timestamps, the lexicographically greater SHA-256 content fingerprint wins. The fingerprint covers source content but excludes local `ingested_at` and notification action. Identical content is a no-op. The SQL `ON CONFLICT ... DO UPDATE ... WHERE` evaluates the rule while PostgreSQL holds the row lock, so two workers cannot overwrite a newer row with an older one by racing.

The hash tie rule is deterministic, not a claim that the chosen content is scientifically newer. Its purpose is to make replay and arrival order produce the same current row when EMSC provides no ordering information. A later EMSC timestamp always takes priority over the hash.

## Kafka offsets and invalid records

The consumer disables automatic offset commits. It commits the source offset synchronously only after PostgreSQL commits. If the database write fails, the offset remains uncommitted, allowing replay after recovery. A database commit can succeed while the offset commit fails; the next delivery is safe because the upsert is idempotent.

Malformed values, unsupported event versions, missing values, and mismatched Kafka keys are sent to `earthquake.events.v1.quarantine`. The quarantine message records the source topic, partition, offset, failure category, byte count, and SHA-256 hashes. It contains no raw event or exception text. The original can be inspected at its source Kafka offset while Kafka still retains it. The source offset advances only after the quarantine producer receives an acknowledgement. If quarantine is unavailable, processing stops without committing that source offset.

The processor currently exits on a database or Kafka failure; supervised restart and bounded retry behavior will be added with service hardening. Quarantine topic access and retention need production configuration before deployment.
