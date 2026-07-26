"""Tier-1 funnel fixes: token-free first onboarding message, the post-run
👍/👎 quality pulse, "applied N" hire-attribution rows, and the next-day
"did you apply?" follow-up sweep."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from app import models
from app.routes import whatsapp
from app.services import apply_followup
from app.settings import settings
from tests.conftest import _TestingSession


PHONE = "27820004444"


def _patch_sends(monkeypatch, sent, buttons, events=None):
    async def fake_send(to, text):
        sent.append(text)

    async def fake_buttons(to, body, btns):
        buttons.append((body, btns))

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_buttons", fake_buttons)
    monkeypatch.setattr(whatsapp, "_record_whatsapp_message", lambda *a, **k: None)
    monkeypatch.setattr(
        whatsapp, "record_server_event",
        (lambda *a, **k: events.append(a)) if events is not None else (lambda *a, **k: None),
    )


def _seed_match_run(db, phone=PHONE, completed_at=None, last_active_at=None):
    job = models.Job(title="Deckhand — 50m MY", role="Deckhand", yacht="MY Test",
                     location="Antibes", status="open")
    db.add(job)
    db.commit()
    db.refresh(job)
    ms = models.MatchSession(
        user_key=phone, status="completed", total_jobs_scanned=1, total_matched=1,
        completed_at=completed_at or datetime.now(timezone.utc),
    )
    db.add(ms)
    db.flush()
    db.add(models.MatchSessionResult(
        session_id=ms.id, job_id=job.id, matched=True, compatibility=90,
        reason="Strong deck background.", strengths=json.dumps([]), gaps=json.dumps([]),
        factor_scores=json.dumps({}),
    ))
    ws = models.WhatsAppSession(
        phone_number=phone, mode="chat", last_match_session_id=ms.id,
        last_active_at=last_active_at or datetime.now(timezone.utc),
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws, ms, job


# ── Leak 1: first onboarding message leads with value, never tokens ───────────


def test_fallback_greeting_has_no_token_or_buy_language():
    low = whatsapp._FALLBACK_GREETING.lower()
    for banned in ("token", "buy", "top up", "r25", "pay"):
        assert banned not in low
    assert "name" in low  # still asks the first onboarding question


def test_onboard_system_prompt_forbids_token_talk_on_first_reply():
    prompt = whatsapp._build_onboard_system({})
    assert "buy tokens" not in prompt.lower()
    assert "NEVER mention tokens" in prompt


# ── 👍/👎 quality pulse ────────────────────────────────────────────────────────


def test_quality_pulse_sends_thumb_buttons(monkeypatch):
    sent, buttons, events = [], [], []
    _patch_sends(monkeypatch, sent, buttons, events)
    monkeypatch.setattr(settings, "MATCH_FEEDBACK_DELAY_SECONDS", 0)

    db = _TestingSession()
    try:
        ws, ms, _job = _seed_match_run(db)
        monkeypatch.setattr(whatsapp, "SessionLocal", _TestingSession)
        asyncio.run(whatsapp._send_match_quality_pulse(PHONE, ms.id))
        assert len(buttons) == 1
        ids = [bid for bid, _t in buttons[0][1]]
        assert ids == ["btn_match_good", "btn_match_bad"]
    finally:
        db.close()


def test_quality_pulse_skipped_when_superseded_by_newer_run(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)
    monkeypatch.setattr(settings, "MATCH_FEEDBACK_DELAY_SECONDS", 0)

    db = _TestingSession()
    try:
        ws, ms, _job = _seed_match_run(db)
        monkeypatch.setattr(whatsapp, "SessionLocal", _TestingSession)
        asyncio.run(whatsapp._send_match_quality_pulse(PHONE, ms.id + 999))
        assert buttons == []
    finally:
        db.close()


def test_pulse_replies_record_run_level_feedback(monkeypatch):
    sent, buttons, events = [], [], []
    _patch_sends(monkeypatch, sent, buttons, events)

    db = _TestingSession()
    try:
        ws, ms, _job = _seed_match_run(db)
        asyncio.run(whatsapp._run_chat(ws, "match feedback good", db))
        assert (PHONE, "match_feedback", f"good:{ms.id}") in events
        assert "draft" in sent[-1].lower()

        asyncio.run(whatsapp._run_chat(ws, "match feedback bad", db))
        assert (PHONE, "match_feedback", f"bad:{ms.id}") in events
        # Bad feedback routes to profile improvement, not a dead end.
        flat_ids = [bid for _b, btns in buttons for bid, _t in btns]
        assert "btn_edit_profile" in flat_ids
    finally:
        db.close()


# ── "applied N" — hire-attribution rows ───────────────────────────────────────


def test_applied_n_records_match_interaction(monkeypatch):
    sent, buttons, events = [], [], []
    _patch_sends(monkeypatch, sent, buttons, events)

    db = _TestingSession()
    try:
        ws, _ms, job = _seed_match_run(db)
        asyncio.run(whatsapp._run_chat(ws, "applied 1", db))
        row = (
            db.query(models.MatchInteraction)
            .filter_by(user_key=PHONE, job_id=job.id, action="applied")
            .first()
        )
        assert row is not None
        assert (PHONE, "match_applied", str(job.id)) in events
        assert job.title in sent[-1]

        # Idempotent on repeat.
        asyncio.run(whatsapp._run_chat(ws, "applied 1", db))
        assert db.query(models.MatchInteraction).filter_by(user_key=PHONE, action="applied").count() == 1
    finally:
        db.close()


def test_apply_followup_button_replies(monkeypatch):
    sent, buttons, events = [], [], []
    _patch_sends(monkeypatch, sent, buttons, events)

    db = _TestingSession()
    try:
        ws, _ms, _job = _seed_match_run(db)
        asyncio.run(whatsapp._run_chat(ws, "applied yes", db))
        assert (PHONE, "apply_followup_reply", "yes") in events
        assert "applied 1" in sent[-1].lower()

        asyncio.run(whatsapp._run_chat(ws, "applied not yet", db))
        assert (PHONE, "apply_followup_reply", "not_yet") in events

        asyncio.run(whatsapp._run_chat(ws, "applied none", db))
        assert (PHONE, "apply_followup_reply", "none_fit") in events
    finally:
        db.close()


# ── Next-day "did you apply?" sweep ───────────────────────────────────────────


def _patch_sweep(monkeypatch, buttons, events):
    async def fake_buttons(to, body, btns):
        buttons.append((to, body, btns))

    monkeypatch.setattr(whatsapp, "_send_whatsapp_buttons", fake_buttons)
    monkeypatch.setattr(whatsapp, "_wa_configured", lambda: True)
    monkeypatch.setattr(apply_followup, "record_server_event", lambda *a: events.append(a))
    monkeypatch.setattr(apply_followup.flags, "is_enabled", lambda name: True)
    import app.database as app_database
    monkeypatch.setattr(app_database, "SessionLocal", _TestingSession)


def test_sweep_sends_once_per_run_inside_service_window(monkeypatch):
    buttons, events = [], []
    _patch_sweep(monkeypatch, buttons, events)

    now = datetime.now(timezone.utc)
    db = _TestingSession()
    try:
        ws, ms, _job = _seed_match_run(
            db,
            completed_at=now - timedelta(hours=20),   # old enough to ask
            last_active_at=now - timedelta(hours=20), # still inside the 23h window
        )
        stats = asyncio.run(apply_followup.run_apply_followups_once())
        assert stats["sent"] == 1
        assert buttons[0][0] == PHONE
        ids = [bid for bid, _t in buttons[0][2]]
        assert ids == ["btn_applied_yes", "btn_applied_notyet", "btn_applied_none"]
        assert (PHONE, "apply_followup_sent", str(ms.id)) in events

        # Second sweep: already asked about this run — no re-send.
        stats2 = asyncio.run(apply_followup.run_apply_followups_once())
        assert stats2["sent"] == 0 and stats2["already_asked"] == 1
    finally:
        db.close()


def test_sweep_skips_outside_service_window_and_fresh_runs(monkeypatch):
    buttons, events = [], []
    _patch_sweep(monkeypatch, buttons, events)

    now = datetime.now(timezone.utc)
    db = _TestingSession()
    try:
        # Outside the 24h service window — Meta would reject the free-form send.
        _seed_match_run(
            db, phone="27820005555",
            completed_at=now - timedelta(hours=30),
            last_active_at=now - timedelta(hours=30),
        )
        # Too fresh — user hasn't had time to apply yet.
        _seed_match_run(
            db, phone="27820006666",
            completed_at=now - timedelta(hours=2),
            last_active_at=now - timedelta(hours=2),
        )
        stats = asyncio.run(apply_followup.run_apply_followups_once())
        assert stats["sent"] == 0
        assert stats["outside_window"] == 1
        assert buttons == []
    finally:
        db.close()
