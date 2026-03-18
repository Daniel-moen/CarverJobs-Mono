"""
CSRF signed-token protection tests.

Rules:
  - GET requests never need a CSRF token.
  - POST/PATCH/DELETE without X-CSRF-Token → 403.
  - POST/PATCH/DELETE with a forged/expired token → 403.
  - POST/PATCH/DELETE with a valid signed token → proceeds normally.
  - GET responses include X-CSRF-Token header with a fresh token.
"""
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.security import require_admin_session, require_session


def _make_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    def override_session():
        return {"sub": "admin", "role": "admin"}

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_session] = override_session
    app.dependency_overrides[require_admin_session] = override_session
    app.state.limiter.enabled = False
    return TestClient(app, raise_server_exceptions=False)


def _cleanup():
    app.dependency_overrides.clear()
    app.state.limiter.enabled = True


def test_get_returns_csrf_header():
    c = _make_client()
    try:
        resp = c.get("/health")
        assert resp.status_code == 200
        assert "X-CSRF-Token" in resp.headers
        token = resp.headers["X-CSRF-Token"]
        assert "." in token
    finally:
        _cleanup()


def test_post_without_csrf_token_rejected():
    c = _make_client()
    try:
        resp = c.post("/auth/logout")
        assert resp.status_code == 403
        assert "CSRF" in resp.json().get("detail", "")
    finally:
        _cleanup()


def test_post_with_wrong_csrf_token_rejected():
    c = _make_client()
    try:
        resp = c.post(
            "/auth/logout",
            headers={"X-CSRF-Token": "totally-wrong-value"},
        )
        assert resp.status_code == 403
    finally:
        _cleanup()


def test_post_with_correct_csrf_token_accepted():
    c = _make_client()
    try:
        resp = c.get("/health")
        token = resp.headers["X-CSRF-Token"]
        resp = c.post("/auth/logout", headers={"X-CSRF-Token": token})
        assert resp.status_code == 200
    finally:
        _cleanup()


def test_csrf_error_response_includes_fresh_token():
    c = _make_client()
    try:
        resp = c.post("/auth/logout")
        assert resp.status_code == 403
        fresh_token = resp.headers.get("X-CSRF-Token", "")
        assert fresh_token and "." in fresh_token
        resp2 = c.post("/auth/logout", headers={"X-CSRF-Token": fresh_token})
        assert resp2.status_code == 200
    finally:
        _cleanup()


def test_delete_without_csrf_rejected():
    c = _make_client()
    try:
        resp = c.delete("/jobs/1")
        assert resp.status_code == 403
    finally:
        _cleanup()


def test_patch_without_csrf_rejected():
    c = _make_client()
    try:
        resp = c.patch("/jobs/1", json={"title": "X"})
        assert resp.status_code == 403
    finally:
        _cleanup()
