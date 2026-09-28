from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app


def test_health_liveness_endpoint():
    client = TestClient(app)
    response = client.get("/health/liveness")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "timestamp" in body


@patch("app.main.build_readiness_report")
def test_health_readiness_endpoint_ok_status(mock_build_report):
    """Test readiness endpoint returns 200 when all components are ok."""
    mock_build_report.return_value = {
        "status": "ok",
        "components": {
            "database": {"status": "ok", "latency_ms": 5.2},
            "postgres_pool": {"status": "ok", "pool_size": 10, "checked_out": 2},
            "redis": {"status": "ok", "latency_ms": 1.8},
            "webhook_dlq": {"status": "ok", "dead_letter_count": 0},
            "audit_database": {"status": "ok", "latency_ms": 3.1},
            "revocation_store": {"status": "ok", "latency_ms": 2.3},
        },
    }

    client = TestClient(app)
    response = client.get("/health/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "components" in body
    assert "timestamp" in body


@patch("app.main.build_readiness_report")
def test_health_readiness_endpoint_warn_status(mock_build_report):
    """Test readiness endpoint returns 200 when some components are warn."""
    mock_build_report.return_value = {
        "status": "warn",
        "components": {
            "database": {"status": "ok", "latency_ms": 5.2},
            "postgres_pool": {"status": "warn", "pool_size": 10, "checked_out": 9},
            "redis": {"status": "ok", "latency_ms": 1.8},
            "webhook_dlq": {"status": "ok", "dead_letter_count": 0},
            "audit_database": {"status": "warn", "error": "Connection timeout"},
            "revocation_store": {"status": "ok", "latency_ms": 2.3},
        },
    }

    client = TestClient(app)
    response = client.get("/health/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "warn"
    assert "components" in body
    assert "timestamp" in body


@patch("app.main.build_readiness_report")
def test_health_readiness_endpoint_down_status(mock_build_report):
    """Test readiness endpoint returns 503 when any component is down."""
    mock_build_report.return_value = {
        "status": "down",
        "components": {
            "database": {"status": "down", "error": "Connection refused"},
            "postgres_pool": {"status": "ok", "pool_size": 10, "checked_out": 2},
            "redis": {"status": "ok", "latency_ms": 1.8},
            "webhook_dlq": {"status": "ok", "dead_letter_count": 0},
            "audit_database": {"status": "ok", "latency_ms": 3.1},
            "revocation_store": {"status": "ok", "latency_ms": 2.3},
        },
    }

    client = TestClient(app)
    response = client.get("/health/readiness")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "down"
    assert "components" in body
    assert "timestamp" in body


def test_legacy_health_endpoint_is_deprecated_and_redirects():
    """Legacy /health now returns 308 redirect to /health/liveness with Deprecation header (BE-041)."""
    client = TestClient(app)
    response = client.get("/health", follow_redirects=False)

    assert response.status_code == 308
    assert response.headers.get("location") == "/health/liveness"
    assert response.headers.get("deprecation") == "true"


# ── Issue #565: cheap liveness / readiness probe routes ─────────────────


def test_health_live_is_cheap_and_db_free():
    """#565: /health/live returns 200 without touching the DB."""
    client = TestClient(app)
    response = client.get("/health/live")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "timestamp" in body


def test_health_live_alias_matches_liveness():
    """#565: /health/liveness stays available as an alias of /health/live."""
    client = TestClient(app)
    live = client.get("/health/live")
    liveness = client.get("/health/liveness")

    assert liveness.status_code == live.status_code == 200
    assert set(liveness.json().keys()) == set(live.json().keys())


def test_health_ready_ok_when_db_up():
    """#565: /health/ready is a trivial DB ping returning 200 when reachable."""
    client = TestClient(app)
    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"]["status"] == "ok"
    assert "latency_ms" in body["database"]
    assert "timestamp" in body


def test_health_ready_returns_503_when_db_down():
    """#565: /health/ready maps a failed DB ping to 503 so probes deregister."""
    client = TestClient(app)
    with patch("app.main._ready_db_ping", side_effect=Exception("connection refused")):
        response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "down"
    assert body["database"]["status"] == "down"
    assert "connection refused" in body["database"]["error"]


def test_probes_do_not_trigger_aggregation(monkeypatch):
    """#565 acceptance: aggregation must stay off the probe path.

    build_readiness_report (pool checks + DLQ count + Redis) powers the
    full /health/readiness report; neither cheap probe may call it.
    """

    def _boom(*args, **kwargs):  # pragma: no cover - failure path
        raise AssertionError("probe triggered DB-heavy aggregation")

    monkeypatch.setattr("app.main.build_readiness_report", _boom)

    client = TestClient(app)
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
