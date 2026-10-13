from typing import cast
from unittest.mock import MagicMock

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg_pool import ConnectionPool

from seismic_stream.api.app import app, create_app


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_checks_database_and_metrics_use_route_template() -> None:
    pool = MagicMock(spec=ConnectionPool)
    with TestClient(create_app(cast(ConnectionPool, pool))) as client:
        assert client.get("/ready").json() == {"status": "ready"}
        pool.connection.return_value.__enter__.return_value.execute.assert_called_with(
            "SELECT 1"
        )
        response = client.get("/api/v1/earthquakes/no%20such%20event")
        assert response.status_code == 422
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert 'seismic_api_requests_total{route="/ready",status_class="2xx"}' in (
            metrics.text
        )
        assert "no such event" not in metrics.text


def test_readiness_reports_missing_or_failed_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
    pool = MagicMock(spec=ConnectionPool)
    pool.connection.side_effect = psycopg.OperationalError("injected outage")
    with TestClient(create_app(cast(ConnectionPool, pool))) as client:
        assert client.get("/ready").status_code == 503
        assert "seismic_api_database_ready 0.0" in client.get("/metrics").text
