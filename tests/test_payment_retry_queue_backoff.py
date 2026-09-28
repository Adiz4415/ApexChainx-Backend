"""Tests for payment retry queue backoff visibility — Issue #240.

Validates that the retry queue endpoint returns computed backoff fields
and that the admin retry-now endpoint bypasses backoff.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints.payments import _compute_next_retry_at
from app.core.security import require_admin, require_engineer
from app.main import app
from app.models.payment import PaymentTransaction

client = TestClient(app)


@pytest.fixture
def _bypass_auth():
    """Retry endpoints are role-gated (BE-022); stub the auth dependencies."""
    app.dependency_overrides[require_engineer] = lambda: SimpleNamespace(
        email="engineer@example.com", id="user_engineer", role="engineer"
    )
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(
        email="admin@example.com", id="user_admin", role="admin"
    )
    yield
    app.dependency_overrides.pop(require_engineer, None)
    app.dependency_overrides.pop(require_admin, None)


class TestComputeNextRetryAt:
    def test_first_retry_30s(self):
        base = datetime(2025, 1, 1, tzinfo=UTC)
        result = _compute_next_retry_at(0, base)
        assert result == base + timedelta(seconds=30)

    def test_second_retry_60s(self):
        base = datetime(2025, 1, 1, tzinfo=UTC)
        result = _compute_next_retry_at(1, base)
        assert result == base + timedelta(seconds=60)

    def test_third_retry_120s(self):
        base = datetime(2025, 1, 1, tzinfo=UTC)
        result = _compute_next_retry_at(2, base)
        assert result == base + timedelta(seconds=120)

    def test_capped_at_1_hour(self, monkeypatch):
        """With a retry budget high enough to reach the cap, delay tops at 3600s."""
        monkeypatch.setattr(
            "app.api.v1.endpoints.payments.PaymentRepository.MAX_RETRIES", 10
        )
        base = datetime(2025, 1, 1, tzinfo=UTC)
        # 30 * 2**6 = 1920 < 3600; 30 * 2**7 = 3840 -> capped at 3600.
        result = _compute_next_retry_at(7, base)
        assert result == base + timedelta(seconds=3600)

    def test_returns_none_at_max_retries(self):
        result = _compute_next_retry_at(3, datetime.now(UTC))
        assert result is None


class TestRetryQueueEndpoint:
    @pytest.mark.usefixtures("_bypass_auth")
    @patch("app.api.v1.endpoints.payments.PaymentRepository")
    def test_returns_retry_queue_items(self, MockRepo):
        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        # _compute_next_retry_at reads PaymentRepository.MAX_RETRIES; the patch
        # replaces the class, so the attribute must be a real int.
        MockRepo.MAX_RETRIES = 3
        now = datetime.now(UTC)
        mock_repo.list.return_value = (
            [
                PaymentTransaction(
                    id="pay_001",
                    transaction_hash="tx1",
                    type="penalty",
                    amount=10.0,
                    asset_code="USDC",
                    from_address="A",
                    to_address="B",
                    status="failed",
                    outage_id="out_001",
                    created_at=now,
                    retry_count=1,
                    last_retried_at=now,
                )
            ],
            1,
        )

        resp = client.get("/api/v1/payments/retry-queue")
        assert resp.status_code == 200
        data = resp.json()
        # CursorPage envelope (#cursor pagination), not a bare list.
        assert data["has_more"] is False
        items = data["items"]
        assert len(items) == 1
        item = items[0]
        assert item["id"] == "pay_001"
        assert item["attempt_count"] == 1
        assert item["backoff_seconds"] == 60
        assert item["next_retry_at"] is not None


class TestRetryNowEndpoint:
    @pytest.mark.usefixtures("_bypass_auth")
    @patch("app.api.v1.endpoints.payments.audit_log")
    @patch("app.api.v1.endpoints.payments.PaymentRepository")
    def test_admin_can_retry_immediately(self, MockRepo, mock_audit):
        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        now = datetime.now(UTC)
        existing = PaymentTransaction(
            id="pay_002",
            transaction_hash="tx2",
            type="penalty",
            amount=20.0,
            asset_code="USDC",
            from_address="A",
            to_address="B",
            status="failed",
            outage_id="out_002",
            created_at=now,
            retry_count=0,
            last_retried_at=None,
        )
        retried = PaymentTransaction(
            id="pay_002",
            transaction_hash="tx2",
            type="penalty",
            amount=20.0,
            asset_code="USDC",
            from_address="A",
            to_address="B",
            status="pending",
            outage_id="out_002",
            created_at=now,
            retry_count=1,
            last_retried_at=now,
        )
        mock_repo.get.return_value = existing
        mock_repo.retry.return_value = retried

        resp = client.post("/api/v1/payments/retry-queue/pay_002/retry")
        assert resp.status_code == 200
        assert resp.json()["retry_count"] == 1
        mock_audit.log.assert_called_once()

    @pytest.mark.usefixtures("_bypass_auth")
    @patch("app.api.v1.endpoints.payments.PaymentRepository")
    def test_returns_404_when_not_found(self, MockRepo):
        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        mock_repo.get.return_value = None

        resp = client.post("/api/v1/payments/retry-queue/nonexistent/retry")
        assert resp.status_code == 404

    @pytest.mark.usefixtures("_bypass_auth")
    @patch("app.api.v1.endpoints.payments.PaymentRepository")
    def test_returns_409_when_max_retries_reached(self, MockRepo):
        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        now = datetime.now(UTC)
        existing = PaymentTransaction(
            id="pay_003",
            transaction_hash="tx3",
            type="penalty",
            amount=30.0,
            asset_code="USDC",
            from_address="A",
            to_address="B",
            status="failed",
            outage_id="out_003",
            created_at=now,
            retry_count=3,
            last_retried_at=now,
        )
        mock_repo.get.return_value = existing
        mock_repo.retry.return_value = None  # max retries

        resp = client.post("/api/v1/payments/retry-queue/pay_003/retry")
        assert resp.status_code == 409
