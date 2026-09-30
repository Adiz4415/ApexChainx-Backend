"""Issue #567 — SLA policy_version participates in cache keys and snapshot metadata.

- build_sla_cache_key keeps embedding the per-object policy version.
- build_analytics_cache_key produces a different key when any severity's
  policy_version changes, and keeps the prefix-based invalidation contract.
- Snapshots persist the composite policy_version and return it to callers.
- After publish_config_for_severity bumps a version, a new cache key is
  derived so stale dashboard entries are naturally bypassed.
"""

import re

import pytest

import app.services.sla.config as sla_config
from app.db.session import SessionLocal
from app.models.orm.sla_snapshot import SLAAnalyticsSnapshotORM
from app.models.sla import SLAConfigUpdateRequest
from app.repositories.sla_repository import SLARepository
from app.services.sla.config import get_all_policy_versions, publish_config_for_severity
from app.services.sla_cache_key import build_analytics_cache_key, build_sla_cache_key, policy_version_marker

# Needs the Postgres service; skips with instructions when it is down (see tests/conftest.py).
pytestmark = [pytest.mark.postgres]

_ORIGINAL_CONFIG = {sev: dict(values) for sev, values in sla_config.SLA_CONFIG.items()}


def _reset_service_state() -> None:
    sla_config.SLA_CONFIG = {sev: dict(values) for sev, values in _ORIGINAL_CONFIG.items()}
    sla_config._policy_versions = {sev: 1 for sev in sla_config.SLA_CONFIG}
    sla_config._publish_tokens = {sev: "" for sev in sla_config.SLA_CONFIG}


def _payload(**overrides) -> SLAConfigUpdateRequest:
    values = {"threshold_minutes": 10, "penalty_per_minute": 200, "reward_base": 900}
    values.update(overrides)
    return SLAConfigUpdateRequest(**values)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.query(SLAAnalyticsSnapshotORM).delete()
        session.commit()
        session.close()
        _reset_service_state()


class TestCacheKeyVersioning:
    def test_marker_changes_when_any_severity_bumps(self, db):
        before = policy_version_marker(get_all_policy_versions(db=db))

        publish_config_for_severity("low", _payload(), expected_token=None, db=db)
        after = policy_version_marker(get_all_policy_versions(db=db))

        assert before != after
        # The low component advanced (ledger is the source of truth; other
        # severities may carry versions from earlier publishes in this DB).
        low_before = next(p for p in before.split(".") if p.startswith("low"))
        low_after = next(p for p in after.split(".") if p.startswith("low"))
        assert int(low_after[3:]) > int(low_before[3:])

    def test_analytics_key_changes_after_publish(self, db):
        key_before = build_analytics_cache_key("dashboard_kpis", get_all_policy_versions(db=db), None, None)

        publish_config_for_severity("high", _payload(), expected_token=None, db=db)
        key_after = build_analytics_cache_key("dashboard_kpis", get_all_policy_versions(db=db), None, None)

        assert key_before != key_after

    def test_analytics_key_keeps_invalidation_prefix(self):
        key = build_analytics_cache_key("dashboard_kpis", {"low": 1}, "critical", "site-1")
        assert key.startswith("dashboard_kpis_")

        key = build_analytics_cache_key("trends", {"low": 3}, 7, "day", "UTC", None, None)
        assert key.startswith("trends_")

    def test_sla_cache_key_embeds_version(self):
        assert build_sla_cache_key("obj-1", "marker", 7) == "sla:obj-1:marker:v7"
        assert build_sla_cache_key("obj-1", "marker", 8) != build_sla_cache_key("obj-1", "marker", 7)


class TestSnapshotPolicyVersion:
    def test_create_snapshot_records_policy_version(self, db):
        publish_config_for_severity("medium", _payload(), expected_token=None, db=db)
        marker = policy_version_marker(get_all_policy_versions(db=db))

        snapshot = SLARepository(db).create_snapshot(snapshot_key="test-versioned")

        assert snapshot.policy_version == marker
        medium = next(p for p in marker.split(".") if p.startswith("medium"))
        assert medium in snapshot.policy_version

    def test_get_latest_snapshot_returns_policy_version(self, db):
        repo = SLARepository(db)
        created = repo.create_snapshot(snapshot_key="test-versioned-read")
        fetched = repo.get_latest_snapshot(snapshot_key="test-versioned-read")

        assert fetched is not None
        assert fetched.policy_version == created.policy_version
        assert fetched.policy_version  # non-empty

    def test_snapshot_checksum_covers_policy_version(self, db):
        repo = SLARepository(db)
        snapshot = repo.create_snapshot(snapshot_key="test-versioned-checksum")

        orm = (
            db.query(SLAAnalyticsSnapshotORM)
            .filter(SLAAnalyticsSnapshotORM.snapshot_key == "test-versioned-checksum")
            .order_by(SLAAnalyticsSnapshotORM.id.desc())
            .first()
        )
        assert orm is not None
        assert orm.policy_version == snapshot.policy_version

        # Tampering with the recorded version must break the checksum.
        orm.policy_version = "critical99.high1.low1.medium1"
        assert orm.compute_checksum() != orm.checksum

    def test_rebuild_snapshot_records_policy_version(self, db):
        snapshot = SLARepository(db).rebuild_snapshot(snapshot_key="test-versioned-rebuild")

        assert snapshot.policy_version
        # Every component is "<severity><version>" with an integer version
        # (multi-digit versions included).
        for part in snapshot.policy_version.split("."):
            assert re.fullmatch(r"(critical|high|low|medium)\d+", part), part
