"""Tests for the security module."""
import pytest
from fastapi import HTTPException
from itsdangerous import URLSafeTimedSerializer

from app.security import (
    hash_password,
    issue_session_token,
    parse_session_token,
    require_admin_session,
    verify_password,
)
from app.settings import settings


# ── Password hashing ─────────────────────────────────────────────────────────

def test_hash_password_returns_bcrypt_string():
    hashed = hash_password("supersecret")
    # bcrypt hashes always start with $2b$ (or $2a$)
    assert hashed.startswith("$2")


def test_hash_password_is_not_plaintext():
    raw = "supersecret"
    assert hash_password(raw) != raw


def test_hash_password_different_salts():
    """Two calls with the same input must produce different hashes (bcrypt salting)."""
    h1 = hash_password("samepassword")
    h2 = hash_password("samepassword")
    assert h1 != h2


def test_verify_password_correct():
    raw = "mypassword"
    hashed = hash_password(raw)
    assert verify_password(raw, hashed) is True


def test_verify_password_wrong():
    hashed = hash_password("correctpassword")
    assert verify_password("wrongpassword", hashed) is False


def test_verify_password_invalid_hash():
    """An invalid/legacy hash string must return False, not raise."""
    assert verify_password("any", "not-a-bcrypt-hash") is False


# ── Session tokens ────────────────────────────────────────────────────────────

def test_issue_and_parse_session_token():
    payload = {"sub": "admin", "role": "admin"}
    token = issue_session_token(payload)
    assert isinstance(token, str)
    parsed = parse_session_token(token)
    assert parsed["sub"] == "admin"
    assert parsed["role"] == "admin"


def test_parse_expired_token_raises_401(monkeypatch):
    """A negative max_age means every token is immediately expired."""
    import app.security as sec_module
    token = issue_session_token({"sub": "admin"})
    # -1 ensures age (>=0) > max_age (-1) is always True → SignatureExpired.
    monkeypatch.setattr(sec_module.settings, "SESSION_TTL_SECONDS", -1)
    with pytest.raises(HTTPException) as exc_info:
        parse_session_token(token)
    assert exc_info.value.status_code == 401


def test_parse_bad_signature_raises_401():
    token = issue_session_token({"sub": "admin"})
    tampered = token[:-4] + "XXXX"
    with pytest.raises(HTTPException) as exc_info:
        parse_session_token(tampered)
    assert exc_info.value.status_code == 401


# ── require_admin_session ─────────────────────────────────────────────────────

def test_require_admin_session_allows_admin():
    session = {"sub": "admin", "role": "admin"}
    result = require_admin_session(session)
    assert result == session


def test_require_admin_session_rejects_non_admin():
    session = {"sub": "viewer", "role": "viewer"}
    with pytest.raises(HTTPException) as exc_info:
        require_admin_session(session)
    assert exc_info.value.status_code == 403
