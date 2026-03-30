"""Tests for /auth/* endpoints."""
import pytest

from app.settings import settings


def test_auth_providers_no_google(auth_client):
    """When Google is not configured the provider list reflects that."""
    resp = auth_client.get("/auth/providers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "google" in body
    # In the test environment GOOGLE_OAUTH_CLIENT_ID is empty.
    assert body["google"]["enabled"] is False
    assert body["google"]["client_id"] is None


def test_login_success(auth_client):
    resp = auth_client.post(
        "/auth/login",
        json={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["user"]["username"] == settings.ADMIN_USERNAME
    assert body["user"]["role"] == "admin"
    # Session cookie should be set.
    assert settings.SESSION_COOKIE_NAME in resp.cookies


def test_login_wrong_password(auth_client):
    resp = auth_client.post(
        "/auth/login",
        json={"username": settings.ADMIN_USERNAME, "password": "wrong"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


def test_login_wrong_username(auth_client):
    resp = auth_client.post(
        "/auth/login",
        json={"username": "nobody", "password": settings.ADMIN_PASSWORD},
    )
    assert resp.status_code == 401


def test_google_login_disabled(auth_client):
    """Google login returns 503 when not configured."""
    resp = auth_client.post("/auth/google", json={"id_token": "fake"})
    assert resp.status_code == 503


def test_logout(auth_client):
    # Log in first to get a cookie.
    login = auth_client.post(
        "/auth/login",
        json={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD},
    )
    assert login.status_code == 200

    resp = auth_client.post("/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_session_endpoint_authenticated(client):
    """With the session override in place /auth/session must return 200."""
    resp = client.get("/auth/session")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["session"]["role"] == "admin"


def test_session_endpoint_unauthenticated(auth_client):
    resp = auth_client.get("/auth/session")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["authenticated"] is False
