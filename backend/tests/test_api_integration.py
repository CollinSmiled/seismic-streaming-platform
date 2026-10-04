"""Historical API behavior over a migrated PostgreSQL database."""

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg_pool import ConnectionPool

from seismic_stream.api.app import create_app
from seismic_stream.api.stream import change_stream
from seismic_stream.ingestion.fixture_producer import load_fixture
from seismic_stream.processor.store import EventStore

CAPTURE = Path(__file__).parent / "fixtures" / "emsc_catalogue_capture.json"


@pytest.fixture
def api_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    base_url = os.getenv("DATABASE_URL")
    if not base_url:
        pytest.skip("set DATABASE_URL to run historical API integration tests")
    name = f"seismic_api_test_{uuid4().hex}"
    test_url = urlunsplit(urlsplit(base_url)._replace(path=f"/{name}"))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    with psycopg.connect(base_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            monkeypatch.setenv("DATABASE_URL", test_url)
            command.upgrade(config, "head")
            with ConnectionPool(test_url, min_size=1, max_size=2) as pool:
                store = EventStore(pool)
                sample = load_fixture(
                    CAPTURE, ingested_at=datetime(2026, 10, 3, 17, tzinfo=UTC)
                )[0]
                for event_id, hour, longitude, latitude in (
                    ("event-a", 0, 179.0, 10.0),
                    ("event-b", 0, -179.0, 10.0),
                    ("event-c", 1, 10.0, 0.0),
                    ("event-d", 2, 20.0, 20.0),
                ):
                    event = sample.model_copy(
                        update={
                            "event_id": event_id,
                            "event_time": datetime(2026, 10, 3, hour, tzinfo=UTC),
                            "longitude": longitude,
                            "latitude": latitude,
                        }
                    )
                    assert store.write(event)
                with TestClient(create_app(pool)) as client:
                    yield client
        finally:
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.mark.integration
def test_keyset_pagination_and_single_event(api_client: TestClient) -> None:
    first = api_client.get("/api/v1/earthquakes", params={"limit": 2})
    assert first.status_code == 200
    assert [event["event_id"] for event in first.json()["items"]] == [
        "event-d",
        "event-c",
    ]
    cursor = first.json()["next_cursor"]
    assert isinstance(cursor, str)

    second = api_client.get(
        "/api/v1/earthquakes", params={"limit": 2, "cursor": cursor}
    )
    assert second.status_code == 200
    assert [event["event_id"] for event in second.json()["items"]] == [
        "event-b",
        "event-a",
    ]
    assert second.json()["next_cursor"] is None

    detail = api_client.get("/api/v1/earthquakes/event-c")
    assert detail.status_code == 200
    assert detail.json()["longitude"] == 10.0
    assert detail.json()["source"] == "EMSC"
    missing = api_client.get("/api/v1/earthquakes/unknown")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


@pytest.mark.integration
def test_time_and_antimeridian_bounds(api_client: TestClient) -> None:
    time_result = api_client.get(
        "/api/v1/earthquakes",
        params={
            "start_time": "2026-10-03T01:00:00Z",
            "end_time": "2026-10-03T02:00:00Z",
        },
    )
    assert [event["event_id"] for event in time_result.json()["items"]] == [
        "event-d",
        "event-c",
    ]

    map_result = api_client.get(
        "/api/v1/earthquakes",
        params={"min_lon": 170, "max_lon": -170, "min_lat": 5, "max_lat": 15},
    )
    assert [event["event_id"] for event in map_result.json()["items"]] == [
        "event-b",
        "event-a",
    ]


@pytest.mark.integration
@pytest.mark.parametrize(
    "parameters",
    [
        {"limit": 0},
        {"limit": 201},
        {"cursor": "not-a-cursor"},
        {"cursor": "a"},
        {"start_time": "2026-10-03T01:00:00"},
        {"start_time": "2026-10-04T00:00:00Z", "end_time": "2026-10-03T00:00:00Z"},
        {"min_lon": 0},
        {"min_lon": 0, "max_lon": 10, "min_lat": 20, "max_lat": 10},
        {"min_lon": 0, "max_lon": 200, "min_lat": 0, "max_lat": 10},
    ],
)
def test_bad_query_returns_validation_error(
    api_client: TestClient, parameters: dict[str, object]
) -> None:
    response = api_client.get("/api/v1/earthquakes", params=parameters)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.integration
def test_database_error_returns_service_unavailable(api_client: TestClient) -> None:
    pool = cast(FastAPI, api_client.app).state.pool
    with pool.connection() as connection:
        connection.execute("DROP TABLE earthquake_events")
    response = api_client.get("/api/v1/earthquakes")
    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "unavailable", "message": "Database is unavailable"}
    }


def test_unconfigured_database_returns_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        response = client.get("/api/v1/earthquakes")
    assert response.status_code == 503


@pytest.mark.integration
def test_change_cursor_creation_revision_and_failed_write(
    api_client: TestClient,
) -> None:
    pool = cast(FastAPI, api_client.app).state.pool
    store = EventStore(pool)
    sample = load_fixture(CAPTURE, ingested_at=datetime(2026, 10, 3, 17, tzinfo=UTC))[0]
    event = sample.model_copy(update={"event_id": "event-new"})
    initial = api_client.get("/api/v1/earthquakes").json()
    assert initial["latest_change_cursor"] == 4
    assert store.write(event)
    assert event.source_updated_at is not None
    revised = event.model_copy(
        update={
            "source_updated_at": event.source_updated_at + timedelta(seconds=1),
            "magnitude": 6.1,
        }
    )
    assert store.write(revised)
    assert not store.write(event)

    # A client at cursor 4 still learns that this is a new event, even after a revision.
    changes = api_client.get("/api/v1/earthquakes/changes", params={"after": 4})
    assert changes.status_code == 200
    assert [
        (item["cursor"], item["kind"], item["event"]["magnitude"])
        for item in changes.json()["items"]
    ] == [(6, "created", 6.1)]
    assert changes.json()["next_cursor"] is None
    after_creation = api_client.get("/api/v1/earthquakes/changes", params={"after": 5})
    assert after_creation.json()["items"][0]["kind"] == "updated"

    with pytest.raises(psycopg.errors.CheckViolation):
        store.write(event.model_copy(update={"event_id": "invalid", "latitude": 91}))
    assert api_client.get("/api/v1/earthquakes").json()["latest_change_cursor"] == 6
    assert (
        api_client.get("/api/v1/earthquakes/changes", params={"after": 6}).json()[
            "items"
        ]
        == []
    )
    for parameters in ({"after": -1}, {"limit": 0}, {"limit": 201}):
        assert (
            api_client.get("/api/v1/earthquakes/changes", params=parameters).status_code
            == 422
        )


@pytest.mark.integration
def test_change_pagination_and_committed_notification(api_client: TestClient) -> None:
    pool = cast(FastAPI, api_client.app).state.pool
    first = api_client.get(
        "/api/v1/earthquakes/changes", params={"after": 0, "limit": 2}
    ).json()
    second = api_client.get(
        "/api/v1/earthquakes/changes",
        params={"after": first["next_cursor"], "limit": 2},
    ).json()
    assert [item["cursor"] for item in first["items"] + second["items"]] == [1, 2, 3, 4]
    assert second["next_cursor"] is None

    sample = load_fixture(CAPTURE, ingested_at=datetime(2026, 10, 3, 17, tzinfo=UTC))[0]
    with psycopg.connect(pool.conninfo, autocommit=True) as listener:
        listener.execute("LISTEN earthquake_changes")
        assert EventStore(pool).write(
            sample.model_copy(update={"event_id": "notified"})
        )
        assert [
            notice.payload for notice in listener.notifies(timeout=2, stop_after=1)
        ] == ["5"]
        assert not EventStore(pool).write(
            sample.model_copy(update={"event_id": "notified"})
        )
        assert list(listener.notifies(timeout=0.1, stop_after=1)) == []


@pytest.mark.integration
def test_sse_replays_committed_changes(api_client: TestClient) -> None:
    import asyncio
    import json

    from fastapi import Request

    pool = cast(FastAPI, api_client.app).state.pool

    class ConnectedRequest:
        disconnected = False

        async def is_disconnected(self) -> bool:
            return self.disconnected

    async def read_stream() -> None:
        request = ConnectedRequest()
        stream = change_stream(cast(Request, request), pool, after=3)
        try:
            assert await anext(stream) == ": connected\n\n"
            message = await anext(stream)
            assert message.startswith("id: 4\nevent: earthquake\ndata: ")
            payload = json.loads(message.split("data: ", 1)[1])
            assert payload["event"]["event_id"] == "event-d"
            pending = asyncio.create_task(anext(stream))
            sample = load_fixture(
                CAPTURE, ingested_at=datetime(2026, 10, 3, 17, tzinfo=UTC)
            )[0]
            assert await asyncio.to_thread(
                EventStore(pool).write,
                sample.model_copy(update={"event_id": "live-new"}),
            )
            live_message = await asyncio.wait_for(pending, timeout=5)
            assert live_message.startswith("id: 5\nevent: earthquake\ndata: ")
            request.disconnected = True
            with pytest.raises(StopAsyncIteration):
                await anext(stream)
        finally:
            await stream.aclose()

    asyncio.run(read_stream())
