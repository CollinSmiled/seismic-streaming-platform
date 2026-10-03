from fastapi.testclient import TestClient

from seismic_stream.api.app import app


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
