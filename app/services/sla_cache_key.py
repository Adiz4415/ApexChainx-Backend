"""Builds SLA cache keys including the policy version, so a config
change invalidates stale cached results instead of serving them until
TTL expiry (#567).
"""

from __future__ import annotations


def build_sla_cache_key(sla_id: str, snapshot_marker: str, policy_version: int) -> str:
    return f"sla:{sla_id}:{snapshot_marker}:v{policy_version}"


def policy_version_marker(policy_versions: dict[str, int]) -> str:
    """Composite marker over every severity's policy version (#567).

    Analytics aggregates cover all severities at once, so the marker must
    change when *any* severity's policy is published. Sorted by severity
    for deterministic keys.
    """
    return ".".join(f"{sev}{policy_versions[sev]}" for sev in sorted(policy_versions))


def build_analytics_cache_key(kind: str, policy_versions: dict[str, int], *parts: object) -> str:
    """Analytics cache key that changes whenever any policy_version changes.

    The returned key still starts with ``kind`` (e.g. ``dashboard_kpis_``),
    so prefix-based invalidation keeps working.
    """
    marker = policy_version_marker(policy_versions)
    suffix = "_".join(str(part) for part in parts if part is not None)
    return f"{kind}_{marker}_{suffix}" if suffix else f"{kind}_{marker}"
