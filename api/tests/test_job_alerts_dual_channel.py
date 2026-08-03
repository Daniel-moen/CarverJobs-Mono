"""Job-alert retention loop: free-form inside Meta's 24h service window,
template outside it.

The point of the split is that the free-form half needs no Meta template
approval, so the retention loop is live today; the template half switches on by
env var alone once the template is approved.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from app import models
from app.routes import whatsapp
from app.services import job_alerts
from app.settings import settings
from tests.conftest import _TestingSession

PHONE = "27820005555"


def _patch(monkeypatch, buttons, events, *, template=""):
    async def fake_buttons(to, body, btns):
        buttons.append((to, body, btns))

    monkeypatch.setattr(whatsapp, "_send_whatsapp_buttons", fake_buttons)
    monkeypatch.setattr(job_alerts, "record_server_event", lambda *a: events.append(a))
    monkeypatch.setattr(job_alerts.flags, "is_enabled", lambda name: True)
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "1234567890")
    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr(settings, "WHATSAPP_JOB_ALERT_TEMPLATE", template)
    import app.database as app_database
    monkeypatch.setattr(app_database, "SessionLocal", _TestingSession)


def _seed(db, *, last_active_at, job_age_hours=2, desired_role="Deckhand",
          last_job_alert_at=None, last_apply_followup_at=None):
    now = datetime.now(timezone.utc)
    db.add(models.Job(
        title="Deckhand — 45m MY", role="Deckhand", yacht="MY Test",
        location="Antibes", status="open",
        created_at=now - timedelta(hours=job_age_hours),
    ))
    db.add(models.CrewProfile(
        user_key=PHONE, profile_slug="tst00001", first_name="Sam",
        desired_role=desired_role,
    ))
    ws = models.WhatsAppSession(
        phone_number=PHONE, mode="chat",
        last_active_at=last_active_at,
        last_job_alert_at=last_job_alert_at,
        last_apply_followup_at=last_apply_followup_at,
        # Older than the seeded job, so the job counts as "new since baseline".
        created_at=now - timedelta(days=3),
    )
    db.add(ws)
    db.commit()
    return ws


# ── Free-form channel: works with no template configured ─────────────────────


def test_recently_active_user_gets_freeform_alert_without_template(monkeypatch):
    buttons, events = [], []
    _patch(monkeypatch, buttons, events, template="")

    now = datetime.now(timezone.utc)
    db = _TestingSession()
    try:
        _seed(db, last_active_at=now - timedelta(hours=5))
        stats = asyncio.run(job_alerts.run_job_alerts_once())

        assert stats["sent"] == 1
        assert stats["sent_freeform"] == 1
        assert stats["sent_template"] == 0
        assert stats["needs_template"] == 0

        to, body, btns = buttons[0]
        assert to == PHONE
        # Free-form copy names the real job rather than a bare count.
        assert "Deckhand — 45m MY" in body
        assert "Sam" in body
        assert [bid for bid, _t in btns][0] == "btn_match_recent"
        assert (PHONE, "job_alert_sent", "freeform:1") in events
    finally:
        db.close()


def test_alert_stamps_session_so_it_does_not_repeat(monkeypatch):
    buttons, events = [], []
    _patch(monkeypatch, buttons, events, template="")

    now = datetime.now(timezone.utc)
    db = _TestingSession()
    try:
        _seed(db, last_active_at=now - timedelta(hours=5))
        assert asyncio.run(job_alerts.run_job_alerts_once())["sent"] == 1
        # Second sweep inside JOB_ALERT_MIN_INTERVAL_HOURS must stay silent.
        stats = asyncio.run(job_alerts.run_job_alerts_once())
        assert stats["sent"] == 0
        assert stats["skipped_recent"] == 1
        assert len(buttons) == 1
    finally:
        db.close()


def test_alert_not_stacked_on_a_just_sent_apply_followup(monkeypatch):
    buttons, events = [], []
    _patch(monkeypatch, buttons, events, template="")

    now = datetime.now(timezone.utc)
    db = _TestingSession()
    try:
        _seed(
            db,
            last_active_at=now - timedelta(hours=2),
            last_apply_followup_at=now - timedelta(hours=1),
        )
        stats = asyncio.run(job_alerts.run_job_alerts_once())
        assert stats["sent"] == 0
        assert stats["skipped_recent"] == 1
        assert buttons == []
    finally:
        db.close()


# ── Template channel: dormant users ──────────────────────────────────────────


def test_dormant_user_skipped_and_counted_when_no_template(monkeypatch):
    buttons, events = [], []
    _patch(monkeypatch, buttons, events, template="")

    now = datetime.now(timezone.utc)
    db = _TestingSession()
    try:
        _seed(db, last_active_at=now - timedelta(days=4))  # outside 23h window
        stats = asyncio.run(job_alerts.run_job_alerts_once())

        assert stats["sent"] == 0
        assert stats["needs_template"] == 1
        assert buttons == []
        # Nothing was stamped, so these users are reached as soon as the
        # template env var is set — no backfill needed.
        ws = db.query(models.WhatsAppSession).filter_by(phone_number=PHONE).first()
        assert ws.last_job_alert_at is None
    finally:
        db.close()


def test_dormant_user_gets_template_once_configured(monkeypatch):
    buttons, events = [], []
    _patch(monkeypatch, buttons, events, template="job_alert_v1")

    sends = []

    async def fake_template(client, phone, first_name, count):
        sends.append((phone, first_name, count))
        return True

    monkeypatch.setattr(job_alerts, "_send_template", fake_template)

    now = datetime.now(timezone.utc)
    db = _TestingSession()
    try:
        _seed(db, last_active_at=now - timedelta(days=4))
        stats = asyncio.run(job_alerts.run_job_alerts_once())

        assert stats["sent"] == 1
        assert stats["sent_template"] == 1
        assert stats["sent_freeform"] == 0
        assert sends == [(PHONE, "Sam", 1)]
        assert buttons == []  # template path never uses the free-form sender
        assert (PHONE, "job_alert_sent", "template:1") in events
    finally:
        db.close()


def test_in_window_user_prefers_freeform_even_when_template_configured(monkeypatch):
    buttons, events = [], []
    _patch(monkeypatch, buttons, events, template="job_alert_v1")

    sends = []

    async def fake_template(client, phone, first_name, count):
        sends.append(phone)
        return True

    monkeypatch.setattr(job_alerts, "_send_template", fake_template)

    now = datetime.now(timezone.utc)
    db = _TestingSession()
    try:
        _seed(db, last_active_at=now - timedelta(hours=3))
        stats = asyncio.run(job_alerts.run_job_alerts_once())

        # Free is free — never pay for a template inside the service window.
        assert stats["sent_freeform"] == 1
        assert sends == []
        assert len(buttons) == 1
    finally:
        db.close()


# ── Guards that must survive the channel split ───────────────────────────────


def test_no_alert_when_no_job_matches_the_desired_role(monkeypatch):
    buttons, events = [], []
    _patch(monkeypatch, buttons, events, template="")

    now = datetime.now(timezone.utc)
    db = _TestingSession()
    try:
        _seed(db, last_active_at=now - timedelta(hours=3), desired_role="Chef")
        stats = asyncio.run(job_alerts.run_job_alerts_once())
        assert stats["sent"] == 0
        assert stats["no_match"] == 1
    finally:
        db.close()


def test_loop_is_inert_without_whatsapp_credentials(monkeypatch):
    buttons, events = [], []
    _patch(monkeypatch, buttons, events, template="")
    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", "")

    now = datetime.now(timezone.utc)
    db = _TestingSession()
    try:
        _seed(db, last_active_at=now - timedelta(hours=3))
        stats = asyncio.run(job_alerts.run_job_alerts_once())
        assert stats["sent"] == 0
        assert buttons == []
    finally:
        db.close()


def test_freeform_body_summarises_the_tail(monkeypatch):
    jobs = [
        models.Job(title=f"Deckhand {i}", role="Deckhand", yacht="MY Test",
                   location="Palma", status="open")
        for i in range(5)
    ]
    body = job_alerts._freeform_body("Sam", jobs)
    assert "5 new jobs" in body
    assert "Deckhand 0 — Palma" in body
    assert "and 2 more" in body
    assert "Deckhand 4" not in body
