"""Durable FDSN scan progress and a single active reconciliation worker."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import psycopg


class ReconciliationBusy(RuntimeError):
    """Another worker already holds the source scan lock."""


class PostgresCheckpoint:
    def __init__(self, connection: psycopg.Connection[tuple[Any, ...]]) -> None:
        self.connection = connection

    def load(self) -> datetime | None:
        row = self.connection.execute(
            """SELECT scanned_at FROM source_reconciliation_checkpoints
               WHERE source = 'EMSC'"""
        ).fetchone()
        return row[0] if row is not None else None

    def save(self, scanned_at: datetime) -> None:
        self.connection.execute(
            """INSERT INTO source_reconciliation_checkpoints (source, scanned_at)
               VALUES ('EMSC', %s)
               ON CONFLICT (source) DO UPDATE SET
                 scanned_at = GREATEST(
                   source_reconciliation_checkpoints.scanned_at,
                   EXCLUDED.scanned_at
                 ),
                 committed_at = now()""",
            (scanned_at,),
        )


@contextmanager
def exclusive_checkpoint(database_url: str) -> Iterator[PostgresCheckpoint]:
    # Session-level lock is released automatically if the worker crashes.
    with psycopg.connect(database_url, autocommit=True) as connection:
        acquired = connection.execute(
            "SELECT pg_try_advisory_lock(2026, 1600)"
        ).fetchone()
        if acquired != (True,):
            raise ReconciliationBusy("another EMSC reconciliation worker is active")
        yield PostgresCheckpoint(connection)
