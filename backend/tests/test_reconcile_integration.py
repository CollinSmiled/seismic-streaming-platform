"""A failed scan replays safely into the current PostgreSQL projection."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from psycopg_pool import ConnectionPool

from seismic_stream.events import EarthquakeEvent
from seismic_stream.ingestion.checkpoint import (
    ReconciliationBusy,
    exclusive_checkpoint,
)
from seismic_stream.ingestion.reconcile import reconcile_once
from seismic_stream.processor.store import EventStore

CAPTURE = Path(__file__).parent / "fixtures" / "emsc_catalogue_capture.json"
FEATURES = json.loads(CAPTURE.read_text(encoding="utf-8"))["features"]
NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


@pytest.mark.integration
def test_missed_events_replay_without_duplicate_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = os.getenv("DATABASE_URL")
    if not base_url:
        pytest.skip("set DATABASE_URL to run reconciliation integration tests")
    name = f"seismic_reconcile_test_{uuid4().hex}"
    test_url = urlunsplit(urlsplit(base_url)._replace(path=f"/{name}"))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"type": "FeatureCollection", "features": FEATURES}
        )

    with psycopg.connect(base_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            monkeypatch.setenv("DATABASE_URL", test_url)
            command.upgrade(config, "head")
            with (
                ConnectionPool(test_url, min_size=1, max_size=2) as pool,
                httpx.Client(transport=httpx.MockTransport(respond)) as client,
            ):
                store = EventStore(pool)
                attempts = 0

                def fail_on_second(event: EarthquakeEvent) -> None:
                    nonlocal attempts
                    attempts += 1
                    if attempts == 2:
                        raise RuntimeError("simulated Kafka outage")
                    store.write(event)

                with exclusive_checkpoint(test_url) as checkpoint:
                    assert checkpoint.load() is None
                    with pytest.raises(RuntimeError, match="Kafka outage"):
                        reconcile_once(checkpoint, client, fail_on_second, now=NOW)
                    assert checkpoint.load() is None
                    with (
                        pytest.raises(ReconciliationBusy),
                        exclusive_checkpoint(test_url),
                    ):
                        pass

                with exclusive_checkpoint(test_url) as checkpoint:
                    assert (
                        reconcile_once(
                            checkpoint,
                            client,
                            store.write,
                            now=NOW + timedelta(minutes=1),
                        )
                        == 2
                    )
                    assert checkpoint.load() == NOW + timedelta(minutes=1)
                    assert (
                        reconcile_once(
                            checkpoint,
                            client,
                            store.write,
                            now=NOW + timedelta(minutes=2),
                        )
                        == 2
                    )
                    assert checkpoint.load() == NOW + timedelta(minutes=2)

                with pool.connection() as connection:
                    assert connection.execute(
                        "SELECT count(*) FROM earthquake_events"
                    ).fetchone() == (2,)
                    assert connection.execute(
                        "SELECT last_cursor FROM earthquake_change_clock WHERE id = 1"
                    ).fetchone() == (2,)
        finally:
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
