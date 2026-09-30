"""Issue #565 — cheap /health/livez and /health/readyz probe endpoints.

- /health/livez must return 200 without touching any dependency (probes stay
  cheap and keep the instance registered even during a DB outage).
- /health/readyz must reflect DB connectivity with a single trivial ping:
  200 when the DB answers, 503 when it does not — without running the full
  readiness report (no pool inspection, DLQ counting, Redis/audit probes).
- The heavy /health/readiness report stays off the probe path.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def test_livez_returns_ok():
    client = TestClient(app)
    response = client.get("/health/livez")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "timestamp" in body


def test_livez_does_not_touch_dependencies():
    """Liveness must stay servable while the database is unreachable."""
    with patch("app.main._ping_database", side_effect=RuntimeError("should not be called")) as ping:
        client = TestClient(app)
        response = client.get("/health/livez")

    assert response.status_code == 200
    ping.assert_not_called()


def test_readyz_ok_when_database_answers():
    client = TestClient(app)
    response = client.get("/health/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "timestamp" in body


def test_readyz_returns_503_when_database_down():
    with patch("app.main._ping_database", side_effect=OSError("connection refused")):
        client = TestClient(app)
        response = client.get("/health/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "down"


def test_readyz_avoids_full_readiness_report():
    """The cheap probe must not trigger the DB-heavy aggregation report."""
    with patch("app.main.build_readiness_report") as heavy_report:
        client = TestClient(app)
        response = client.get("/health/readyz")

    assert response.status_code == 200
    heavy_report.assert_not_called()


def test_liveness_still_served():
    """The original liveness route keeps working alongside livez."""
    client = TestClient(app)
    response = client.get("/health/liveness")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
