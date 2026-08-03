"""Win-back nudges for users no other proactive loop reaches: onboarding
drop-outs and onboarded-but-never-matched.

Two stages, both free-form inside Meta's 24h service window (no template):
an early "did you want to finish?" and a last-chance send before it closes.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from app import models
from app.routes import whatsapp
from app.services import window_winback
from app.settings import settings
from tests.conftest import _TestingSession

PHONE = "27820006666"


def _patch(monkeypatch, sent, buttons, events):
    async def fake_send(to, text):
        sent.append((to, text))

    async def fake_buttons(to, body, btns):
        buttons.append((to, body, btns))

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_buttons", fake_buttons)
    monkeypatch.setattr(whatsapp, "_wa_configured", lambda: True)
    monkeypatch.setattr(window_winback, "record_server_event", lambda *a: events.append(a))
    monkeypatch.setattr(window_winback.flags, "is_enabled", lambda name: True)
    import app.database as app_database
    monkeypatch.setattr(app_database, "SessionLocal", _TestingSession)


def _seed(db, *, mode="onboarding", silent_hours=4, partial=None,
          last_winback_at=None, match_session_id=None):
    now = datetime.now(timezone.utc)
    ws = models.WhatsAppSession(
        phone_number=PHONE,
        mode=mode,
        partial_profile=json.dumps(partial if partial is not None else {"firstName": "Sam"}),
        last_active_at=now - timedelta(hours=silent_hours),
        last_winback_at=last_winback_at,
        last_match_session_id=match_session_id,
    )
    db.add(ws)
    db.commit()
    return ws


def _reload(db):
    db.expire_all()
    return db.query(models.WhatsAppSession).filter_by(phone_number=PHONE).first()


# ── Stage 1: the early "did you finish?" nudge ───────────────────────────────


def test_onboarding_dropout_nudged_a_few_hours_later(monkeypatch):
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)

    db = _TestingSession()
    try:
        _seed(db, mode="onboarding", silent_hours=4)
        stats = asyncio.run(window_winback.run_window_winbacks_once())

        assert stats["sent"] == 1
        assert stats["sent_early"] == 1
        to, text = sent[0]
        assert to == PHONE
        assert "Sam" in text
        # Plain text mid-onboarding: buttons would compete with the AI's question.
        assert buttons == []
        assert (PHONE, "window_winback_sent", "early:onboarding") in events
    finally:
        db.close()


def test_early_nudge_not_sent_before_the_threshold(monkeypatch):
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)

    db = _TestingSession()
    try:
        _seed(db, mode="onboarding", silent_hours=1)
        stats = asyncio.run(window_winback.run_window_winbacks_once())
        assert stats["sent"] == 0
        assert stats["too_early"] == 1
        assert sent == []
    finally:
        db.close()


def test_early_nudge_sent_only_once_per_silent_stretch(monkeypatch):
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)

    db = _TestingSession()
    try:
        _seed(db, mode="onboarding", silent_hours=4)
        assert asyncio.run(window_winback.run_window_winbacks_once())["sent"] == 1
        stats = asyncio.run(window_winback.run_window_winbacks_once())
        assert stats["sent"] == 0
        assert stats["already_nudged"] == 1
        assert len(sent) == 1
    finally:
        db.close()


def test_replying_re_arms_the_nudge(monkeypatch):
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)

    now = datetime.now(timezone.utc)
    db = _TestingSession()
    try:
        # Nudged once, then the user replied, then went quiet again.
        _seed(
            db, mode="onboarding", silent_hours=4,
            last_winback_at=now - timedelta(hours=30),
        )
        stats = asyncio.run(window_winback.run_window_winbacks_once())
        assert stats["sent"] == 1
    finally:
        db.close()


def test_copy_counts_the_remaining_questions(monkeypatch):
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)

    db = _TestingSession()
    try:
        # Three of four required fields already collected.
        _seed(db, mode="onboarding", silent_hours=4, partial={
            "firstName": "Sam", "desiredRole": "Deckhand", "currentLocation": "Antibes",
        })
        asyncio.run(window_winback.run_window_winbacks_once())
        assert "1 answer" in sent[0][1]
    finally:
        db.close()


# ── Stage 2: last chance before the window closes ────────────────────────────


def test_last_chance_nudge_fires_late_in_the_window(monkeypatch):
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)

    now = datetime.now(timezone.utc)
    db = _TestingSession()
    try:
        # Early nudge already went out at the 3h mark; now they're at 21h.
        _seed(
            db, mode="onboarding", silent_hours=21,
            last_winback_at=now - timedelta(hours=18),
        )
        stats = asyncio.run(window_winback.run_window_winbacks_once())
        assert stats["sent"] == 1
        assert stats["sent_last_chance"] == 1
        assert (PHONE, "window_winback_sent", "last_chance:onboarding") in events
    finally:
        db.close()


def test_no_third_nudge_after_the_last_chance(monkeypatch):
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)

    now = datetime.now(timezone.utc)
    db = _TestingSession()
    try:
        _seed(
            db, mode="onboarding", silent_hours=22,
            # Last-chance already sent at the 20h mark.
            last_winback_at=now - timedelta(hours=2),
        )
        stats = asyncio.run(window_winback.run_window_winbacks_once())
        assert stats["sent"] == 0
        assert sent == []
    finally:
        db.close()


def test_nothing_sent_once_the_window_has_closed(monkeypatch):
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)

    db = _TestingSession()
    try:
        _seed(db, mode="onboarding", silent_hours=30)
        stats = asyncio.run(window_winback.run_window_winbacks_once())
        assert stats["sent"] == 0
        assert stats["window_closed"] == 1
        assert sent == []
    finally:
        db.close()


# ── Onboarded but never matched ──────────────────────────────────────────────


def test_chat_user_with_no_match_run_gets_a_match_prompt(monkeypatch):
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)

    db = _TestingSession()
    try:
        _seed(db, mode="chat", silent_hours=21)
        stats = asyncio.run(window_winback.run_window_winbacks_once())

        assert stats["sent"] == 1
        assert stats["sent_last_chance"] == 1
        _to, _body, btns = buttons[0]
        assert [bid for bid, _t in btns][0] == "btn_find_matches"
        assert (PHONE, "window_winback_sent", "last_chance:no_match") in events
    finally:
        db.close()


def test_chat_user_gets_no_early_nudge(monkeypatch):
    """The early stage is for onboarding drop-outs only."""
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)

    db = _TestingSession()
    try:
        _seed(db, mode="chat", silent_hours=5)
        stats = asyncio.run(window_winback.run_window_winbacks_once())
        assert stats["sent"] == 0
        assert stats["too_early"] == 1
    finally:
        db.close()


def test_user_with_a_real_match_run_is_left_to_the_apply_followup(monkeypatch):
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)

    now = datetime.now(timezone.utc)
    db = _TestingSession()
    try:
        ms = models.MatchSession(
            user_key=PHONE, status="completed", total_jobs_scanned=10,
            total_matched=3, completed_at=now - timedelta(hours=21),
        )
        db.add(ms)
        db.commit()
        db.refresh(ms)
        _seed(db, mode="chat", silent_hours=21, match_session_id=ms.id)

        stats = asyncio.run(window_winback.run_window_winbacks_once())
        assert stats["sent"] == 0
        assert stats["has_match_run"] == 1
        assert sent == [] and buttons == []
    finally:
        db.close()


def test_empty_match_run_still_gets_nudged(monkeypatch):
    """A run that matched nothing is not a reason to stay silent."""
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)

    now = datetime.now(timezone.utc)
    db = _TestingSession()
    try:
        ms = models.MatchSession(
            user_key=PHONE, status="completed", total_jobs_scanned=10,
            total_matched=0, completed_at=now - timedelta(hours=21),
        )
        db.add(ms)
        db.commit()
        db.refresh(ms)
        _seed(db, mode="chat", silent_hours=21, match_session_id=ms.id)

        stats = asyncio.run(window_winback.run_window_winbacks_once())
        assert stats["sent"] == 1
    finally:
        db.close()


# ── Cross-loop spacing ───────────────────────────────────────────────────────


def test_no_nudge_right_after_another_loop_pinged_them(monkeypatch):
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)

    now = datetime.now(timezone.utc)
    db = _TestingSession()
    try:
        ws = _seed(db, mode="chat", silent_hours=21)
        ws.last_job_alert_at = now - timedelta(hours=1)
        db.commit()

        stats = asyncio.run(window_winback.run_window_winbacks_once())
        assert stats["sent"] == 0
        assert stats["already_nudged"] == 1
    finally:
        db.close()


def test_sweep_is_inert_when_whatsapp_is_not_configured(monkeypatch):
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)
    monkeypatch.setattr(whatsapp, "_wa_configured", lambda: False)

    db = _TestingSession()
    try:
        _seed(db, mode="onboarding", silent_hours=4)
        stats = asyncio.run(window_winback.run_window_winbacks_once())
        assert stats["sent"] == 0
        assert sent == []
    finally:
        db.close()


def test_onboarding_nudge_is_recorded_in_the_chat_history(monkeypatch):
    """So the AI's next turn reads as a conversation, not a non-sequitur."""
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)

    db = _TestingSession()
    try:
        _seed(db, mode="onboarding", silent_hours=4)
        asyncio.run(window_winback.run_window_winbacks_once())

        history = json.loads(_reload(db).history)
        assert history[-1]["role"] == "assistant"
        assert history[-1]["content"] == sent[0][1]
    finally:
        db.close()


def test_stamp_is_written_so_the_loop_is_idempotent(monkeypatch):
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)

    db = _TestingSession()
    try:
        _seed(db, mode="onboarding", silent_hours=4)
        asyncio.run(window_winback.run_window_winbacks_once())
        assert _reload(db).last_winback_at is not None
    finally:
        db.close()


def test_thresholds_are_configurable(monkeypatch):
    sent, buttons, events = [], [], []
    _patch(monkeypatch, sent, buttons, events)
    monkeypatch.setattr(settings, "WINDOW_WINBACK_EARLY_HOURS", 8)

    db = _TestingSession()
    try:
        _seed(db, mode="onboarding", silent_hours=4)
        assert asyncio.run(window_winback.run_window_winbacks_once())["sent"] == 0
    finally:
        db.close()
