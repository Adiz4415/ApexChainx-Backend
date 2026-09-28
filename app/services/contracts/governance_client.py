"""Soroban contract governance client.

Provides typed wrappers around the contract's governance operations:
propose_admin, accept_admin, cancel_admin_proposal, renounce_admin,
propose_operator, accept_operator.

There is no real Soroban execution path yet. In ``local_adapter`` mode the
client returns deterministic stubs that are always labeled ``simulated: True``
so they can never be mistaken for on-chain completions. Because fabricated
hashes reported as success are worse than an honest 501, every operation is
additionally gated behind ``GOVERNANCE_ENABLED`` (off by default): with the
flag off the client raises instead of returning a payload, and the admin
endpoints surface that as 501 not_implemented.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.core.config import settings


class GovernanceError(Exception):
    """Raised when a governance operation fails."""


class GovernanceNotImplementedError(GovernanceError):
    """Governance is disabled (or the operation has no execution path)."""


def _stub_tx_hash(operation: str, address: str) -> str:
    """Return a deterministic stub transaction hash for local_adapter mode."""
    raw = f"{settings.SLA_CONTRACT_ADDRESS}:{operation}:{address}"
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _ensure_enabled() -> None:
    """Refuse to fabricate results when governance is disabled.

    The local_adapter path cannot talk to Soroban; every "success" it produces
    is simulated. Returning one by default misleads operators and security
    reviewers into believing an on-chain admin transfer occurred (see
    THREAT_MODEL.md F-1), so the caller must opt in explicitly.
    """
    if not getattr(settings, "GOVERNANCE_ENABLED", False):
        raise GovernanceNotImplementedError(
            "Governance operations are disabled. No contract execution path is "
            "implemented; set GOVERNANCE_ENABLED=true only for local simulation."
        )


def _simulated(operation: str, address: str) -> dict[str, Any]:
    """Common envelope for local_adapter responses, marked simulated."""
    return {
        "tx_hash": _stub_tx_hash(operation, address),
        "simulated": True,
        "contract_address": settings.SLA_CONTRACT_ADDRESS,
        "network": settings.STELLAR_NETWORK,
    }


def propose_admin(new_admin_address: str) -> dict[str, Any]:
    """Initiate a two-step admin transfer.

    Returns the transaction hash and the pending admin address.
    """
    if not new_admin_address:
        raise GovernanceError("new_admin_address is required")

    _ensure_enabled()

    if settings.CONTRACT_EXECUTION_MODE == "local_adapter":
        result = _simulated("propose_admin", new_admin_address)
        result["pending_admin"] = new_admin_address
        result["status"] = "proposed"
        return result

    raise GovernanceError("soroban_rpc mode not yet implemented for propose_admin")


def accept_admin() -> dict[str, Any]:
    """Complete an admin transfer (called by the proposed new admin).

    Returns the transaction hash.
    """
    _ensure_enabled()

    if settings.CONTRACT_EXECUTION_MODE == "local_adapter":
        result = _simulated("accept_admin", "current")
        result["status"] = "accepted"
        return result

    raise GovernanceError("soroban_rpc mode not yet implemented for accept_admin")


def cancel_admin_proposal() -> dict[str, Any]:
    """Cancel a pending admin proposal."""
    _ensure_enabled()

    if settings.CONTRACT_EXECUTION_MODE == "local_adapter":
        result = _simulated("cancel_admin_proposal", "current")
        result["status"] = "cancelled"
        return result

    raise GovernanceError("soroban_rpc mode not yet implemented for cancel_admin_proposal")


def renounce_admin() -> dict[str, Any]:
    """Renounce admin role permanently."""
    _ensure_enabled()

    if settings.CONTRACT_EXECUTION_MODE == "local_adapter":
        result = _simulated("renounce_admin", "current")
        result["status"] = "renounced"
        return result

    raise GovernanceError("soroban_rpc mode not yet implemented for renounce_admin")


def propose_operator(new_operator_address: str) -> dict[str, Any]:
    """Initiate a two-step operator transfer.

    Returns the transaction hash and the pending operator address.
    """
    if not new_operator_address:
        raise GovernanceError("new_operator_address is required")

    _ensure_enabled()

    if settings.CONTRACT_EXECUTION_MODE == "local_adapter":
        result = _simulated("propose_operator", new_operator_address)
        result["pending_operator"] = new_operator_address
        result["status"] = "proposed"
        return result

    raise GovernanceError("soroban_rpc mode not yet implemented for propose_operator")


def accept_operator() -> dict[str, Any]:
    """Complete an operator transfer (called by the proposed new operator)."""
    _ensure_enabled()

    if settings.CONTRACT_EXECUTION_MODE == "local_adapter":
        result = _simulated("accept_operator", "current")
        result["status"] = "accepted"
        return result

    raise GovernanceError("soroban_rpc mode not yet implemented for accept_operator")
