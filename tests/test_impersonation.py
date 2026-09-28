"""Tests for admin user impersonation endpoint."""

import pytest

from app.core.security import get_password_hash
from app.db.session import SessionLocal
from app.models.auth import LoginRequest, RegisterRequest
from app.models.enums import Role
from app.models.orm.user import UserORM
from app.repositories.user_repository import UserRepository
from app.services.auth_store import AuthStore


def _seed_user(email: str, password: str, full_name: str, role: Role) -> None:
    """Create a user with an explicit role directly in the DB.

    Public registration always creates engineers (role self-assignment was
    removed), so tests needing a privileged user must seed one the same way
    the admin-only creation endpoint does.
    """
    db = SessionLocal()
    try:
        repo = UserRepository(db)
        if not repo.get_by_email(email):
            repo.create(
                user_id=f"user_{email.split('@')[0]}"[:60],
                email=email,
                hashed_password=get_password_hash(password),
                full_name=full_name,
                role=role,
            )
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def admin_headers(client):
    """Seed an admin user and return auth headers with a valid token."""
    db = SessionLocal()
    try:
        email = f"imp-admin-{id(object())}@example.com"
        password = "Admin123!"
        _seed_user(email, password, "Admin User", Role.admin)
        session = AuthStore.login(LoginRequest(email=email, password=password), db=db)
        yield {
            "Authorization": f"Bearer {session.access_token}",
            "email": email,
            "user_id": session.user.id,
        }
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def regular_user_headers(client):
    """Register a regular engineer user and return auth headers."""
    db = SessionLocal()
    try:
        email = f"imp-regular-{id(object())}@example.com"
        password = "Regular123!"
        AuthStore.register(
            RegisterRequest(
                email=email,
                password=password,
                full_name="Regular User",
            ),
            db=db,
        )
        session = AuthStore.login(LoginRequest(email=email, password=password), db=db)
        yield {
            "Authorization": f"Bearer {session.access_token}",
            "email": email,
            "user_id": session.user.id,
        }
    finally:
        db.rollback()
        db.close()


class TestImpersonation:
    def test_admin_can_impersonate_regular_user(self, client, admin_headers, regular_user_headers):
        payload = {
            "user_id": regular_user_headers["user_id"],
            "reason": "Troubleshooting user-reported SLA calculation issue",
        }
        response = client.post(
            "/api/v1/auth/impersonate",
            json=payload,
            headers={"Authorization": admin_headers["Authorization"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        # The impersonation token should have act=admin claim
        assert data.get("acting_as") == regular_user_headers["user_id"]

    def test_impersonation_token_can_access_me(self, client, admin_headers, regular_user_headers):
        payload = {
            "user_id": regular_user_headers["user_id"],
            "reason": "Debugging access issue",
        }
        response = client.post(
            "/api/v1/auth/impersonate",
            json=payload,
            headers={"Authorization": admin_headers["Authorization"]},
        )
        assert response.status_code == 200
        imp_token = response.json()["access_token"]

        # Use the impersonation token to call /auth/me
        me_response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {imp_token}"})
        assert me_response.status_code == 200
        me_data = me_response.json()
        assert me_data["id"] == regular_user_headers["user_id"]

    def test_cannot_impersonate_another_admin(self, client, admin_headers):
        # Seed a second admin directly (public registration cannot create admins)
        db = SessionLocal()
        try:
            admin2_email = f"imp-admin2-{id(object())}@example.com"
            _seed_user(admin2_email, "Admin123!", "Admin Two", Role.admin)
            admin2 = db.query(UserORM).filter(UserORM.email == admin2_email).first()
            admin2_id = admin2.id if admin2 else "unknown"
        finally:
            db.rollback()
            db.close()

        payload = {
            "user_id": admin2_id,
            "reason": "Testing admin impersonation guard",
        }
        response = client.post(
            "/api/v1/auth/impersonate",
            json=payload,
            headers={"Authorization": admin_headers["Authorization"]},
        )
        # Cannot impersonate another admin
        assert response.status_code == 403

    def test_reason_is_required(self, client, admin_headers, regular_user_headers):
        payload = {
            "user_id": regular_user_headers["user_id"],
            "reason": "",
        }
        response = client.post(
            "/api/v1/auth/impersonate",
            json=payload,
            headers={"Authorization": admin_headers["Authorization"]},
        )
        assert response.status_code == 422  # validation error for empty reason

    def test_non_admin_cannot_impersonate(self, client, regular_user_headers):
        payload = {
            "user_id": "some-user-id",
            "reason": "Should not work",
        }
        response = client.post(
            "/api/v1/auth/impersonate",
            json=payload,
            headers={"Authorization": regular_user_headers["Authorization"]},
        )
        assert response.status_code == 403

    def test_impersonation_without_auth_returns_401(self, client):
        payload = {
            "user_id": "some-user-id",
            "reason": "Should not work",
        }
        response = client.post("/api/v1/auth/impersonate", json=payload)
        assert response.status_code == 401
