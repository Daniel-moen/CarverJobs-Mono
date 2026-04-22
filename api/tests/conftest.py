"""
Shared test fixtures.

Two clients are provided:
  - `client`      — authenticated (session dependency overridden); use for all
                    routes that require a logged-in admin.
  - `auth_client` — raw (no overrides); use for tests that exercise the actual
                    login / logout / session endpoints.
"""
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.security import optional_session, require_admin_session, require_session
from app.settings import settings

SQLALCHEMY_TEST_URL = "sqlite:///:memory:"

# StaticPool ensures all connections share the same in-memory database so that
# tables created by create_all() are visible to every subsequent query.
_engine = create_engine(
    SQLALCHEMY_TEST_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _override_get_db():
    db = _TestingSession()
    try:
        yield db
    finally:
        db.close()


def _override_require_session():
    return {"sub": "admin", "role": "admin"}


@pytest.fixture(autouse=True)
def _disable_auto_login(monkeypatch):
    """Real auth tests must not depend on a developer .env enabling auto-login."""
    monkeypatch.setattr(settings, "AUTO_LOGIN_AS_ADMIN", False)


@pytest.fixture(autouse=True)
def _reset_db():
    """Re-create all tables before each test so each test starts clean."""
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


def _wait_db_ready(client: TestClient, *, timeout_s: float = 30.0) -> None:
    """Lifespan runs DB init in a background task; non-exempt routes 503 until ready."""
    deadline = time.monotonic() + timeout_s
    while not getattr(client.app.state, "db_ready", False):
        if time.monotonic() > deadline:
            raise RuntimeError("Timed out waiting for app.state.db_ready")
        time.sleep(0.02)


def _seed_csrf(client):
    """
    Make a GET request to obtain a signed CSRF token from the response
    header, then wire it as a default header for all subsequent requests.
    """
    resp = client.get("/health")
    token = resp.headers.get("X-CSRF-Token", "")
    client.headers.update({"X-CSRF-Token": token})


@pytest.fixture()
def client():
    """TestClient with DB + session auth overridden."""
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[optional_session] = _override_require_session
    app.dependency_overrides[require_session] = _override_require_session
    app.dependency_overrides[require_admin_session] = _override_require_session
    app.state.limiter.enabled = False
    with TestClient(app, raise_server_exceptions=True) as c:
        _wait_db_ready(c)
        _seed_csrf(c)
        yield c
    app.dependency_overrides.clear()
    app.state.limiter.enabled = True


@pytest.fixture()
def auth_client():
    """TestClient with only the DB overridden — real auth path."""
    app.dependency_overrides[get_db] = _override_get_db
    app.state.limiter.enabled = False
    with TestClient(app, raise_server_exceptions=True) as c:
        _wait_db_ready(c)
        _seed_csrf(c)
        yield c
    app.dependency_overrides.clear()
    app.state.limiter.enabled = True
