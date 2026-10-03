"""Exercise upgrade and rollback in an isolated temporary PostgreSQL database."""

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql


@pytest.mark.integration
def test_fresh_migration_constraints_and_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = os.getenv("DATABASE_URL")
    if not base_url:
        pytest.skip("set DATABASE_URL to run PostgreSQL migration checks")

    name = f"seismic_migration_test_{uuid4().hex}"
    parsed_url = urlsplit(base_url)
    test_url = urlunsplit(parsed_url._replace(path=f"/{name}"))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    with psycopg.connect(base_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            monkeypatch.setenv("DATABASE_URL", test_url)
            command.upgrade(config, "head")
            with psycopg.connect(test_url, autocommit=True) as database:
                assert database.execute(
                    "SELECT to_regclass('earthquake_events')"
                ).fetchone() == ("earthquake_events",)
                with pytest.raises(psycopg.errors.CheckViolation):
                    database.execute(
                        """INSERT INTO earthquake_events
                           (event_id, source, event_time, ingested_at, latitude,
                            longitude, content_sha256)
                           VALUES (%s, 'EMSC', now(), now(), 91, 0, %s)""",
                        ("invalid-latitude", "0" * 64),
                    )
                with pytest.raises(psycopg.errors.CheckViolation):
                    database.execute(
                        """INSERT INTO earthquake_events
                           (event_id, source, event_time, ingested_at, latitude,
                            longitude, magnitude, content_sha256)
                           VALUES (%s, 'EMSC', now(), now(), 0, 0,
                                   'Infinity'::float8, %s)""",
                        ("invalid-magnitude", "0" * 64),
                    )

            command.downgrade(config, "base")
            with psycopg.connect(test_url) as database:
                assert database.execute(
                    "SELECT to_regclass('earthquake_events')"
                ).fetchone() == (None,)
            command.upgrade(config, "head")
            with psycopg.connect(test_url) as database:
                assert database.execute(
                    "SELECT to_regclass('earthquake_events')"
                ).fetchone() == ("earthquake_events",)
        finally:
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
