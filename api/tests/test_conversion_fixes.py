"""Conversion fixes: honest job-post reward messaging, abandoned-checkout
recovery, the 4-field onboarding, and durable funnel events."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from app import models
from app.routes import whatsapp
from app.services import checkout_recovery, payments
from app.settings import settings
from tests.conftest import _TestingSession


PHONE = "27820002222"


def _patch_sends(monkeypatch, sent, buttons):
    async def fake_send(to, text):
        sent.append(text)

    async def fake_buttons(to, body, btns):
        buttons.append((body, btns))

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_buttons", fake_buttons)
    monkeypatch.setattr(whatsapp, "_record_whatsapp_message", lambda *a, **k: None)


class _FakeJob:
    title = "Deckhand — 45m MY"
    role = "Deckhand"
    location = "Antibes"


# ── Job-post reward messaging ──────────────────────────────────────────────────


def test_job_posted_confirmation_when_token_granted(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    asyncio.run(whatsapp._send_job_posted_confirmation(
        PHONE, _FakeJob(), {"granted": True, "balance": 4, "remaining": 3},
    ))

    assert len(sent) == 1
    assert "You earned *1 token*" in sent[0]
    assert "*4* tokens" in sent[0]
    assert not buttons


def test_job_posted_confirmation_when_monthly_cap_reached(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    asyncio.run(whatsapp._send_job_posted_confirmation(
        PHONE, _FakeJob(), {"granted": False, "balance": 0, "remaining": 0},
    ))

    assert len(sent) == 1
    assert "earned" not in sent[0].split("Thanks")[0]  # no false token promise
    assert "You earned *1 token*" not in sent[0]
    assert str(settings.FREE_JOB_POST_TOKENS_PER_MONTH) in sent[0]
    assert "live" in sent[0].lower()
    # Buy Tokens button shown at the moment the free loop closes.
    assert len(buttons) == 1
    assert ("cmd_subscribe", "Buy Tokens") in buttons[0][1]


# ── Abandoned-checkout recovery ────────────────────────────────────────────────


def _seed_sub(db, user_key, ref, *, age, status="pending", channel="whatsapp",
              amount="220.00", reminder_sent_at=None, checkout_url=None):
    sub = models.Subscription(
        user_key=user_key,
        m_payment_id=ref,
        status=status,
        amount=amount,
        frequency=0,
        channel=channel,
        checkout_url=checkout_url,
        reminder_sent_at=reminder_sent_at,
        created_at=datetime.now(timezone.utc) - age,
    )
    db.add(sub)
    db.commit()
    return sub


def _patch_recovery(monkeypatch, buttons, events):
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "12345")
    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", "token")

    async def fake_buttons(to, body, btns):
        buttons.append((to, body, btns))

    monkeypatch.setattr(whatsapp, "_send_whatsapp_buttons", fake_buttons)
    monkeypatch.setattr(
        checkout_recovery, "record_server_event",
        lambda user_key, name, value=None: events.append((user_key, name, value)),
    )


def test_checkout_recovery_selects_whatsapp_window_only(monkeypatch):
    buttons, events = [], []
    _patch_recovery(monkeypatch, buttons, events)

    db = _TestingSession()
    try:
        eligible = _seed_sub(db, "27820000001", "co-1", age=timedelta(hours=2),
                             checkout_url="https://pay.yoco.test/co_1")
        _seed_sub(db, "27820000002", "co-2", age=timedelta(minutes=10))       # too fresh
        _seed_sub(db, "27820000003", "co-3", age=timedelta(hours=30))          # past 24h window
        _seed_sub(db, "web@example.com", "co-4", age=timedelta(hours=2), channel="web")
        _seed_sub(db, "27820000005", "co-5", age=timedelta(hours=2), status="completed")
        _seed_sub(db, "27820000006", "co-6", age=timedelta(hours=2),
                  reminder_sent_at=datetime.now(timezone.utc))                 # already reminded
        # Legacy row (no channel recorded) from a known WhatsApp user.
        db.add(models.WhatsAppSession(phone_number="27820000007", mode="chat"))
        db.commit()
        legacy = _seed_sub(db, "27820000007", "co-7", age=timedelta(hours=2), channel=None)

        stats = asyncio.run(checkout_recovery.run_checkout_recovery_once(db))

        assert stats["sent"] == 2
        assert {b[0] for b in buttons} == {"27820000001", "27820000007"}

        # Pack details + resume link come from config/DB, never hardcoded copy.
        body_1 = next(b[1] for b in buttons if b[0] == "27820000001")
        assert "Standard" in body_1 and "20 tokens" in body_1 and "R220" in body_1
        assert "https://pay.yoco.test/co_1" in body_1
        body_7 = next(b[1] for b in buttons if b[0] == "27820000007")
        assert "buy tokens" in body_7.lower()  # no stored URL → command fallback

        # Every nudge carries a Buy Tokens button.
        assert all(("cmd_subscribe", "Buy Tokens") in b[2] for b in buttons)

        # Durable events: abandoned + reminder_sent per nudged checkout.
        names = [e[1] for e in events]
        assert names.count("checkout_abandoned") == 2
        assert names.count("checkout_reminder_sent") == 2

        db.refresh(eligible)
        db.refresh(legacy)
        assert eligible.reminder_sent_at is not None
        assert legacy.reminder_sent_at is not None

        # Second sweep: everyone already reminded — one nudge max, ever.
        stats2 = asyncio.run(checkout_recovery.run_checkout_recovery_once(db))
        assert stats2["sent"] == 0
        assert len(buttons) == 2
    finally:
        db.close()


def test_checkout_recovery_noops_when_unconfigured(monkeypatch):
    buttons, events = [], []
    _patch_recovery(monkeypatch, buttons, events)
    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", "")

    db = _TestingSession()
    try:
        _seed_sub(db, "27820000011", "co-11", age=timedelta(hours=2))
        stats = asyncio.run(checkout_recovery.run_checkout_recovery_once(db))
    finally:
        db.close()

    assert stats["sent"] == 0
    assert not buttons


def test_checkout_creates_pending_with_channel_and_url(monkeypatch):
    """create_checkout must persist channel + payment URL for the recovery sweep."""

    class _FakeResp:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "co_test", "redirectUrl": "https://pay.yoco.test/co_test"}

    async def fake_post(*a, **k):
        return _FakeResp()

    monkeypatch.setattr(settings, "YOCO_SECRET_KEY", "sk_test")
    monkeypatch.setattr(payments._http, "post", fake_post)

    db = _TestingSession()
    try:
        url = asyncio.run(payments.create_checkout(db, PHONE, 20, channel="whatsapp"))
        assert url == "https://pay.yoco.test/co_test"
        sub = db.query(models.Subscription).filter_by(user_key=PHONE).first()
        assert sub.status == "pending"
        assert sub.channel == "whatsapp"
        assert sub.checkout_url == "https://pay.yoco.test/co_test"
        assert sub.reminder_sent_at is None
    finally:
        db.close()


# ── 4-field onboarding ─────────────────────────────────────────────────────────


def test_required_onboard_fields_are_the_four_activation_fields():
    assert whatsapp.REQUIRED_ONBOARD_FIELDS == [
        "firstName", "desiredRole", "currentLocation", "yearsExperience",
    ]
    # Dropped fields stay collectable, just never block signup.
    for field in ("lastName", "nationality", "certifications"):
        assert field in whatsapp.OPTIONAL_ONBOARD_FIELDS
        assert field in whatsapp._FIELD_QUESTIONS


def test_onboarding_retry_escalates_to_explicit_question(monkeypatch):
    """Two consecutive extraction failures on the same field must escalate to
    the dead-simple explicit prompt instead of looping "didn't catch that"."""

    async def failing_openai(system, history, user_message, *, model=None):
        return {}

    monkeypatch.setattr(whatsapp, "_call_openai", failing_openai)

    db = _TestingSession()
    try:
        ws = models.WhatsAppSession(
            phone_number="27820000021",
            mode="onboarding",
            history=json.dumps([
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "welcome"},
            ]),
            partial_profile="{}",
        )
        db.add(ws)
        db.commit()

        first = asyncio.run(whatsapp._run_onboarding(ws, "🤷", db))
        assert "didn't quite catch that" in first

        second = asyncio.run(whatsapp._run_onboarding(ws, "🤷", db))
        assert "didn't quite catch that" not in second
        assert whatsapp._FIELD_QUESTIONS["firstName"] in second
    finally:
        db.close()


# ── Durable funnel events ──────────────────────────────────────────────────────


def _capture_events(monkeypatch, module):
    events = []
    monkeypatch.setattr(
        module, "record_server_event",
        lambda user_key, name, value=None: events.append((user_key, name, value)),
    )
    return events


def test_new_session_records_durable_onboard_started(monkeypatch):
    events = _capture_events(monkeypatch, whatsapp)
    db = _TestingSession()
    try:
        whatsapp._get_or_create_session("27820000031", db)
    finally:
        db.close()
    names = [e[1] for e in events]
    assert "wa_signup" in names
    assert ("27820000031", "onboard_started", "whatsapp") in events


def test_pack_picker_records_shown_event_and_anchor_line(monkeypatch):
    events = _capture_events(monkeypatch, whatsapp)
    lists = []

    async def fake_list(to, **kwargs):
        lists.append(kwargs)

    monkeypatch.setattr(whatsapp, "_send_whatsapp_list", fake_list)
    monkeypatch.setattr(whatsapp, "_record_whatsapp_message", lambda *a, **k: None)
    monkeypatch.setattr(whatsapp, "get_credit_balance", lambda db, key: 0)
    monkeypatch.setattr(whatsapp, "_is_first_purchase", lambda db, key: False)
    monkeypatch.setattr(payments, "yoco_configured", lambda: True)

    db = _TestingSession()
    try:
        asyncio.run(whatsapp._send_token_pack_picker(PHONE, db))
    finally:
        db.close()

    assert (PHONE, "pack_picker_shown", "whatsapp") in events
    # Value anchor derived from the pack badged most popular in settings.
    popular = next(p for p in settings.TOKEN_PACKAGES if "popular" in str(p.get("badge", "")).lower())
    body = lists[0]["body"]
    assert f"{int(popular['tokens'])}-token pack" in body
    assert f"R{float(popular['price']):g}" in body
    assert "per match run" in body


def test_onboarding_completion_records_first_match_auto_run(monkeypatch):
    events = _capture_events(monkeypatch, whatsapp)
    sent = []

    async def fake_send(to, text):
        sent.append(text)

    async def fake_match_run(phone, graph_id="", scope="all"):
        return None

    async def fake_cta(to, **kwargs):
        sent.append(kwargs.get("body", ""))

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_cta_url", fake_cta)
    monkeypatch.setattr(whatsapp, "_record_whatsapp_message", lambda *a, **k: None)
    monkeypatch.setattr(whatsapp, "_make_magic_link", lambda phone, db, redirect_to=None: "https://x/wa/tok")
    monkeypatch.setattr(whatsapp, "get_credit_balance", lambda db, key: 2)
    monkeypatch.setattr(whatsapp, "_run_match_command_background", fake_match_run)

    async def done_openai(system, history, user_message, *, model=None):
        return {"message": "That's a wrap!", "done": True, "updates": {"yearsExperience": "3"}}

    monkeypatch.setattr(whatsapp, "_call_openai", done_openai)

    db = _TestingSession()
    try:
        ws = models.WhatsAppSession(
            phone_number="27820000041",
            mode="onboarding",
            history=json.dumps([
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "welcome"},
            ]),
            partial_profile=json.dumps({
                "firstName": "Sam", "desiredRole": "Deckhand", "currentLocation": "Cape Town",
            }),
        )
        db.add(ws)
        db.commit()

        async def _drive():
            reply = await whatsapp._run_onboarding(ws, "3 years", db)
            pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            return reply

        reply = asyncio.run(_drive())
    finally:
        db.close()

    # Completion now sends the welcome + docs CTA itself and returns None.
    assert reply is None
    assert any("Welcome to the fleet" in t for t in sent)
    names = [e[1] for e in events]
    assert "onboard_completed" in names
    assert ("27820000041", "first_match_auto_run", "whatsapp") in events


def test_post_match_enrichment_only_nudges_when_certs_missing(monkeypatch):
    sent = []

    async def fake_send(to, text):
        sent.append(text)

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_record_whatsapp_message", lambda *a, **k: None)

    db = _TestingSession()
    try:
        db.add(models.CrewProfile(user_key="27820000051", profile_slug="slug0051"))
        db.add(models.CrewProfile(user_key="27820000052", profile_slug="slug0052", certifications="STCW"))
        db.commit()

        asyncio.run(whatsapp._send_post_match_enrichment("27820000051", db))
        assert len(sent) == 1
        assert "certifications" in sent[0].lower()
        assert "edit profile" in sent[0].lower()

        asyncio.run(whatsapp._send_post_match_enrichment("27820000052", db))
        assert len(sent) == 1  # certs present → no nudge
    finally:
        db.close()
