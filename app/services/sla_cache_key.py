"""Builds SLA cache keys including the policy version, so a config
change invalidates stale cached results instead of serving them until
TTL expiry.
"""

from app.services.sla.config import max_policy_version


def build_sla_cache_key(sla_id: str, snapshot_marker: str, policy_version: int) -> str:
    return f"sla:{sla_id}:{snapshot_marker}:v{policy_version}"


def build_sla_aggregate_cache_key(scope: str, policy_version: int | None = None) -> str:
    """Return a version-stamped cache key for aggregate analytics (#567).

    The key embeds the policy version so any publish that bumps a severity's
    version shifts every aggregate key immediately: stale entries become
    unreachable instead of being served until TTL expiry. Pass an explicit
    ``policy_version`` to force a specific stamp; otherwise the current
    in-process version is used (callers with a DB session should pass
    ``max_policy_version(db)``).
    """
    if policy_version is None:
        policy_version = max_policy_version()
    return f"{scope}:v{policy_version}"
