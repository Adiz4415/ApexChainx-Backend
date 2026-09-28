import pytest
from fastapi.testclient import TestClient

from app.core.config import settings as app_settings
from app.core.rate_limiter import SimpleRateLimiter, rate_limiter
from app.db.session import SessionLocal
from app.main import app


def _flush_rate_limiter_state() -> None:
    """Clear every store the auth rate limiter can leak state into.

    The limiter is a module singleton, and its state outlives a single test in
    two ways: Redis keys namespaced ``auth_rate_limiter:*`` persist across pytest
    invocations, and ``SimpleRateLimiter._shared`` is class-level, so the
    in-memory fallback (used whenever Redis is bypassed) persists across tests
    in the same process. Leftovers surface as spurious 429s on register/login
    because TestClient always presents the same source IP. The circuit-breaker
    timestamp is process state too and must not leak a Redis outage into a
    later test.
    """
    SimpleRateLimiter._shared.clear()
    if hasattr(rate_limiter, "disabled_until"):
        rate_limiter.disabled_until = None
    client = getattr(rate_limiter, "client", None)
    if client is None or not app_settings.USE_REDIS_RATE_LIMITER:
        return
    try:
        for pattern in ("auth_rate_limiter:*", "webhook_breaker:open:*"):
            batch: list[str] = []
            for key in client.scan_iter(match=pattern):
                batch.append(key)
                if len(batch) >= 500:
                    client.delete(*batch)
                    batch.clear()
            if batch:
                client.delete(*batch)
    except Exception:
        # Redis unreachable: the limiter itself degrades to the in-memory
        # fallback, so tests must not fail on cleanup.
        pass


@pytest.fixture(autouse=True)
def _isolated_rate_limiter():
    _flush_rate_limiter_state()
    yield
    _flush_rate_limiter_state()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def settings():
    """Yield the app Settings singleton, restoring mutated fields afterwards.

    Tests use this to flip flags such as GOVERNANCE_ENABLED or
    CONTRACT_EXECUTION_MODE for the duration of one test; the snapshot keeps
    the mutation from leaking into later tests in the same process.
    """
    from app.core.config import settings as _settings

    snapshot = dict(_settings.__dict__)
    yield _settings
    _settings.__dict__.clear()
    _settings.__dict__.update(snapshot)
