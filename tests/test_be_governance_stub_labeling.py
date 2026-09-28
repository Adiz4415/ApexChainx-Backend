import pytest
from app.services.contracts.governance_client import (
    propose_admin,
    accept_admin,
    renounce_admin,
    GovernanceNotImplementedError,
)


@pytest.fixture
def admin_headers():
    """Bypass auth — override require_admin with a fake admin (same as the
    admin endpoint test suite). The endpoint must then surface disabled
    governance as 501 rather than a fabricated success payload."""
    from datetime import UTC, datetime

    from app.core.security import require_admin
    from app.main import app
    from app.models.auth import AuthUser, Role

    fake_admin = AuthUser(
        id="admin_test",
        email="admin_test@example.com",
        full_name="Test Admin",
        role=Role.admin,
        created_at=datetime.now(UTC),
    )
    app.dependency_overrides[require_admin] = lambda: fake_admin
    yield {"X-Test-Admin": "1"}
    app.dependency_overrides.pop(require_admin, None)


@pytest.mark.parametrize(
    "fn,args",
    [
        (propose_admin, ("GADDRESS123",)),
        (accept_admin, ()),
        (renounce_admin, ()),
    ],
)
def test_governance_ops_raise_when_disabled(settings, fn, args):
    """With GOVERNANCE_ENABLED off (the default), every governance op
    must fail loudly rather than fabricate a success response."""
    settings.GOVERNANCE_ENABLED = False
    with pytest.raises(GovernanceNotImplementedError):
        fn(*args)


def test_simulated_response_is_explicitly_labeled(settings):
    """When explicitly enabled for local testing, responses must be
    clearly marked as simulated and never claim on-chain completion."""
    settings.GOVERNANCE_ENABLED = True
    settings.CONTRACT_EXECUTION_MODE = "local_adapter"
    result = propose_admin("GADDRESS123")
    assert result["simulated"] is True
    assert "status" in result


def test_admin_endpoint_returns_501_when_not_implemented(client, settings, admin_headers):
    """Disabled governance surfaces as 501, not a fabricated success."""
    settings.GOVERNANCE_ENABLED = False
    response = client.post(
        "/api/v1/admin/propose-admin",
        json={"new_admin_address": "GADDRESS123"},
        headers=admin_headers,
    )
    assert response.status_code == 501
    body = response.json()
    assert body["errors"][0]["error"] == "not_implemented"
