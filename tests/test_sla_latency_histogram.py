"""Tests for SLA computation latency histogram — Issue #241.

Validates that compute_device_sla() records latency to the histogram
metric and that the metric is available on the Prometheus endpoint.
"""

from unittest.mock import MagicMock, patch

from app.core.security import require_engineer
from app.services.metrics import INSTANCE_ID, _SLA_LATENCY_BUCKETS, metrics


class TestSLALatencyHistogram:
    @patch("app.services.sla_service.record_histogram")
    @patch("app.services.sla_service.SLAOrchestrator")
    def test_histogram_recorded_on_no_outages(self, MockOrchestrator, mock_record):
        from app.services.sla_service import compute_device_sla

        orch = MagicMock()
        MockOrchestrator.return_value = orch
        from datetime import datetime

        orch.parse_period.return_value = (datetime(2025, 3, 1), datetime(2025, 4, 1))
        orch.get_outages_for_device.return_value = []
        db = MagicMock()

        compute_device_sla(db, "dev-1", "2025-03")

        mock_record.assert_called()
        call_args = mock_record.call_args
        assert call_args[0][0] == "sla_computation_latency_seconds"
        assert call_args[0][1] >= 0  # latency >= 0
        assert call_args[1]["tags"]["device_id"] == "dev-1"

    @patch("app.services.sla_service.record_histogram")
    @patch("app.services.sla_service.SLAOrchestrator")
    def test_histogram_recorded_on_with_outages(self, MockOrchestrator, mock_record):
        from app.services.sla_service import compute_device_sla

        orch = MagicMock()
        MockOrchestrator.return_value = orch
        from datetime import datetime

        orch.parse_period.return_value = (datetime(2025, 3, 1), datetime(2025, 4, 1))
        outage = MagicMock()
        outage.id = "o-1"
        outage.site_id = "s-1"
        outage.site_name = "Site A"
        outage.detected_at = datetime(2025, 3, 5, 10, 0)
        outage.resolved_at = datetime(2025, 3, 5, 12, 0)
        outage.severity = "high"
        orch.get_outages_for_device.return_value = [outage]
        orch.calculate_mttr.return_value = 120.0
        orch.calculate_availability.return_value = 99.5
        orch.check_sla_violations.return_value = False
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        compute_device_sla(db, "dev-1", "2025-03")

        mock_record.assert_called()
        call_args = mock_record.call_args
        assert call_args[0][0] == "sla_computation_latency_seconds"
        assert call_args[0][1] >= 0


class TestSLALatencyBuckets:
    def test_buckets_match_spec(self):
        assert _SLA_LATENCY_BUCKETS == [0.01, 0.05, 0.1, 0.5, 1.0, 5.0]

    def test_histogram_bucket_tracking(self):
        """Verify that the global metrics registry tracks buckets correctly."""
        metrics.record_histogram("test_latency", 0.03, buckets=[0.01, 0.05, 0.1])
        metrics.record_histogram("test_latency", 0.07, buckets=[0.01, 0.05, 0.1])
        metrics.record_histogram("test_latency", 0.15, buckets=[0.01, 0.05, 0.1])

        summary = metrics.get_metrics_summary()
        # Keys carry the instance tag (see metrics._make_key, #336), so look
        # up the tagged series, not the bare metric name.
        key = f"test_latency{{instance={INSTANCE_ID}}}"
        buckets = summary.get("histogram_buckets", {}).get(key, {})
        # Prometheus semantics: an observation increments exactly one bucket —
        # the first bound >= value — so unreached bounds are simply absent.
        assert buckets.get(0.01, 0) == 0  # 0.03 > 0.01
        assert buckets.get(0.05) == 1  # 0.03 landed here
        assert buckets.get(0.1) == 1  # 0.07 landed here (0.03 did not)
        # 0.15 exceeds every bound, so it is only reflected in the count (+Inf).


class TestPrometheusEndpointIncludesHistogram:
    def test_latency_histogram_in_prometheus_output(self):
        from types import SimpleNamespace

        from fastapi.testclient import TestClient

        from app.main import app

        # /metrics/prometheus is gated on the engineer role (BE-022); bypass
        # auth the same way the other endpoint tests do.
        app.dependency_overrides[require_engineer] = lambda: SimpleNamespace(
            email="metrics@example.com", id="user_metrics", role="engineer"
        )
        client = TestClient(app)
        try:
            # Record a metric first
            from app.services.sla_service import compute_device_sla

            with patch("app.services.sla_service.SLAOrchestrator") as MockOrch:
                orch = MagicMock()
                MockOrch.return_value = orch
                from datetime import datetime

                orch.parse_period.return_value = (datetime(2025, 3, 1), datetime(2025, 4, 1))
                orch.get_outages_for_device.return_value = []
                db = MagicMock()
                compute_device_sla(db, "dev-prom", "2025-03")

            resp = client.get("/api/v1/metrics/prometheus")
            assert resp.status_code == 200
            text = resp.text
            assert "sla_computation_latency_seconds" in text
        finally:
            app.dependency_overrides.pop(require_engineer, None)
