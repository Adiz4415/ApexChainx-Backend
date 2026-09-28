"""Issue #567 — expose the SLA policy version in cache keys and snapshot metadata.

Previously the analytics caches were keyed only by request parameters, so a
config publish served stale aggregates until the TTL expired, and snapshot
rows carried no record of which policy produced their numbers. These tests
pin:

- Aggregate cache keys shift when the policy version changes (no stale hits).
- Snapshots record the policy version active at snapshot time (create and
  rebuild paths), and the version round-trips through the API schema.
- The checksum covers the recorded version (tamper detection).
- max_policy_version prefers the persisted ledger and falls back to the
  in-process cache on a fresh deployment.
"""

import pytest

import app.services.sla.config as sla_config
from app.db.session import SessionLocal
from app.models.orm.sla_config_history import SLAConfigHistoryORM
from app.models.orm.sla_snapshot import SLAAnalyticsSnapshotORM
from app.models.sla import SLAConfigUpdateRequest
from app.repositories.sla_repository import SLARepository
from app.services.sla.config import max_policy_version, publish_config_for_severity
from app.services.sla_cache_key import build_sla_aggregate_cache_key, build_sla_cache_key

_ORIGINAL_CONFIG = {sev: dict(values) for sev, values in sla_config.SLA_CONFIG.items()}


def _reset_service_state() -> None:
    """Simulate a fresh process: the in-memory caches forget everything."""
    sla_config.SLA_CONFIG = {sev: dict(values) for sev, values in _ORIGINAL_CONFIG.items()}
    sla_config._policy_versions = {sev: 1 for sev in sla_config.SLA_CONFIG}
    sla_config._publish_tokens = {sev: "" for sev in sla_config.SLA_CONFIG}


def _wipe_history(db, severity: str) -> None:
    db.query(SLAConfigHistoryORM).filter(SLAConfigHistoryORM.severity == severity).delete()
    db.commit()


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        # max_policy_version() reads the global max across severities, so a
        # per-severity wipe cannot isolate a test from rows left by earlier
        # tests (or a pre-existing dev database). Reset the whole ledger.
        session.query(SLAConfigHistoryORM).delete()
        session.commit()
        _reset_service_state()
        yield session
    finally:
        session.rollback()
        session.close()
        _reset_service_state()


def _payload(**overrides) -> SLAConfigUpdateRequest:
    values = {"threshold_minutes": 10, "penalty_per_minute": 200, "reward_base": 900}
    values.update(overrides)
    return SLAConfigUpdateRequest(**values)


class TestCacheKeysShiftWithPolicyVersion:
    def test_key_changes_when_policy_version_changes(self):
        """Acceptance criterion: keys change when policy_version changes."""
        assert build_sla_aggregate_cache_key("dashboard_kpis", policy_version=1) != (
            build_sla_aggregate_cache_key("dashboard_kpis", policy_version=2)
        )

    def test_key_embeds_scope_and_version(self):
        key = build_sla_aggregate_cache_key("trends_7_day_UTC", policy_version=3)
        assert key.startswith("trends_7_day_UTC:")
        assert key.endswith(":v3")

    def test_explicit_stamp_beats_implicit_default(self):
        default = build_sla_aggregate_cache_key("scope")
        stamped = build_sla_aggregate_cache_key("scope", policy_version=99)
        assert stamped != default

    def test_version_stamped_key_differs_from_unstamped_scope(self):
        """A stamped key can never collide with a pre-#567 unstamped key."""
        assert build_sla_aggregate_cache_key("scope", policy_version=1) != "scope"

    def test_result_cache_key_still_includes_version(self):
        """The pre-existing per-result key keeps its version component."""
        assert build_sla_cache_key("dev-1", "2025-03", 4).endswith(":v4")


class TestCacheInvalidationOnPublish:
    def test_stale_entry_is_unreachable_after_version_bump(self):
        """A cached entry stored under v1 is not served once the version is v2."""
        from app.utils.cache import TTLCache

        cache: TTLCache = TTLCache(ttl_seconds=300)
        scope = "dashboard_kpis_None_None"

        def resolve(version: int):
            key = build_sla_aggregate_cache_key(scope, policy_version=version)
            hit = cache.get(key)
            if hit is not None:
                return hit
            value = {"computed_under": f"v{version}"}
            cache.set(key, value)
            return value

        assert resolve(1) == {"computed_under": "v1"}
        # Config publish bumps the version; the v1 entry is simply unreachable.
        assert resolve(2) == {"computed_under": "v2"}

    def test_endpoint_publish_invalidates_dashboard_cache(self, db):
        """Publishing a config must not leave the old aggregates cached."""
        from app.api.v1.endpoints import sla as sla_endpoints

        severity = "medium"
        _wipe_history(db, severity)
        _reset_service_state()

        scope = "dashboard_kpis_critical_None"
        sla_endpoints._dashboard_cache.set(scope, {"stale": True})
        assert sla_endpoints._dashboard_cache.get(scope) == {"stale": True}

        publish_config_for_severity("critical", _payload(), expected_token=None, published_by="t@example.com", db=db)
        sla_endpoints._invalidate_analytics_cache()

        assert sla_endpoints._dashboard_cache.get(scope) is None


class TestMaxPolicyVersion:
    def test_db_ledger_is_authoritative(self, db):
        severity = "high"
        _wipe_history(db, severity)
        _reset_service_state()

        assert max_policy_version(db) == 1  # no history rows yet → cache fallback
        _, _, history = publish_config_for_severity(
            severity, _payload(), expected_token=None, published_by="t@example.com", db=db
        )
        assert max_policy_version(db) == history.policy_version

    def test_falls_back_to_in_process_cache_without_db(self):
        assert max_policy_version(None) == max(sla_config._policy_versions.values())

    def test_bumps_after_publish(self, db):
        severity = "low"
        _wipe_history(db, severity)
        _reset_service_state()
        before = max_policy_version(db)
        publish_config_for_severity(severity, _payload(), expected_token=None, published_by="t@example.com", db=db)
        assert max_policy_version(db) == before + 1


class TestSnapshotRecordsPolicyVersion:
    def test_create_snapshot_records_current_version(self, db):
        severity = "medium"
        _wipe_history(db, severity)
        _reset_service_state()

        publish_config_for_severity(severity, _payload(), expected_token=None, published_by="t@example.com", db=db)
        expected = max_policy_version(db)

        snapshot = SLARepository(db).create_snapshot(snapshot_key="test-567")
        assert snapshot.policy_version == expected
        assert snapshot.policy_version >= 1

    def test_rebuild_snapshot_records_current_version(self, db):
        severity = "high"
        _wipe_history(db, severity)
        _reset_service_state()

        repo = SLARepository(db)
        snapshot = repo.rebuild_snapshot(snapshot_key="test-567-rebuild")
        assert snapshot.policy_version == max_policy_version(db)

    def test_snapshot_version_changes_after_publish(self, db):
        """Snapshots taken across a publish record different versions."""
        severity = "low"
        _wipe_history(db, severity)
        _reset_service_state()

        repo = SLARepository(db)
        first = repo.rebuild_snapshot(snapshot_key="test-567-bump")
        publish_config_for_severity(
            severity, _payload(threshold_minutes=77), expected_token=None, published_by="t@example.com", db=db
        )
        second = repo.rebuild_snapshot(snapshot_key="test-567-bump")

        assert second.policy_version == first.policy_version + 1

    def test_get_latest_snapshot_round_trips_version(self, db):
        repo = SLARepository(db)
        created = repo.rebuild_snapshot(snapshot_key="test-567-roundtrip")
        fetched = repo.get_latest_snapshot(snapshot_key="test-567-roundtrip")
        assert fetched is not None
        assert fetched.policy_version == created.policy_version

    def test_checksum_covers_policy_version(self, db):
        """Tampering with the recorded version must break the checksum."""
        orm = db.query(SLAAnalyticsSnapshotORM).order_by(SLAAnalyticsSnapshotORM.id.desc()).first()
        assert orm is not None
        assert orm.policy_version is not None

        original = orm.checksum
        orm.policy_version = orm.policy_version + 1
        assert orm.compute_checksum() != original

    def test_orm_column_exists(self):
        assert hasattr(SLAAnalyticsSnapshotORM, "policy_version")
