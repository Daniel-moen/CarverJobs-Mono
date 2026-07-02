"""Tests for the funnel-instrumentation and reliability changes:

- magic-link auth marks tokens used (previously never written → unmeasurable)
- global janitor fails long-stuck 'running' match sessions
- /agent/stats exposes the durable funnel block
- job-alert role matching (cheap substring matcher, no LLM)
"""
from datetime import datetime, timedelta, timezone

from app.models import MatchSession, WhatsAppMagicToken
from app.services.job_alerts import _matching_jobs, _role_tokens
from app.services.job_retention import fail_stuck_match_sessions
from app.settings import settings

from .conftest import _TestingSession


def test_magic_auth_marks_token_used(client):
    db = _TestingSession()
    db.add(WhatsAppMagicToken(
        token="tok_test_used_flag",
        phone_number="27000000001",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    db.commit()

    resp = client.get("/wa/auth/tok_test_used_flag")
    assert resp.status_code == 200

    db.expire_all()
    record = db.query(WhatsAppMagicToken).filter_by(token="tok_test_used_flag").first()
    assert record.used is True
    assert record.used_at is not None
    db.close()


def test_magic_auth_stays_reusable_within_ttl(client):
    db = _TestingSession()
    db.add(WhatsAppMagicToken(
        token="tok_test_reusable",
        phone_number="27000000002",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    ))
    db.commit()
    db.close()

    assert client.get("/wa/auth/tok_test_reusable").status_code == 200
    assert client.get("/wa/auth/tok_test_reusable").status_code == 200


def test_janitor_fails_stuck_running_sessions_only():
    db = _TestingSession()
    db.add(MatchSession(
        user_key="27000000003", status="running",
        total_jobs_scanned=0, total_matched=0,
        created_at=datetime.now(timezone.utc) - timedelta(hours=5),
    ))
    db.add(MatchSession(
        user_key="27000000004", status="running",
        total_jobs_scanned=0, total_matched=0,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    ))
    db.commit()

    flipped = fail_stuck_match_sessions(db)
    assert flipped == 1

    stale = db.query(MatchSession).filter_by(user_key="27000000003").first()
    fresh = db.query(MatchSession).filter_by(user_key="27000000004").first()
    assert stale.status == "failed"
    assert fresh.status == "running"
    db.close()


def test_agent_stats_includes_funnel_block(client, monkeypatch):
    monkeypatch.setattr(settings, "AGENT_API_TOKEN", "test-agent-token")
    resp = client.get("/agent/stats", headers={"Authorization": "Bearer test-agent-token"})
    assert resp.status_code == 200
    funnel = resp.json()["funnel"]
    for key in (
        "wa_signups_total",
        "activated_first_match_within_24h",
        "d7_returned",
        "unique_token_buyers",
        "server_events",
    ):
        assert key in funnel


def test_job_alert_role_matching():
    assert _role_tokens("Deckhand, Engineer / ETO") == ["deckhand", "engineer", "eto"]

    class _J:
        def __init__(self, role, title):
            self.role = role
            self.title = title

    jobs = [
        _J("Deckhand", "Junior Deckhand — 45m MY"),
        _J("Chief Stewardess", "Chief Stew needed"),
        _J("", "Sole Engineer 38m"),
    ]
    assert len(_matching_jobs(jobs, "Deckhand")) == 1
    assert len(_matching_jobs(jobs, "Stew")) == 1
    assert len(_matching_jobs(jobs, "Engineer")) == 1
    assert _matching_jobs(jobs, "") == []
