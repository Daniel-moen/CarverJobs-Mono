"""P0 conversion fixes: payments that must never be silently lost, and the
Meta-compliant STOP/START opt-out that gates every proactive loop.

Three families here:
  * superseded checkouts — opening a second checkout must not make the first
    one uncreditable if the buyer goes back and pays it;
  * webhook metadata fallback — an unknown reference or a mismatched amount
    credits from the signed metadata instead of dropping the payment;
  * opt-out — STOP sets the flag before command routing, START clears it, and
    all four proactive loops skip the user.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from app import models
from app.routes import subscription as sub_routes
from app.routes import whatsapp
from app.services import apply_followup, checkout_recovery, job_alerts, payment_reconcile, payments, window_winback
from app.services.credits import get_credit_balance
from app.settings import settings
from tests.conftest import _TestingSession

PHONE = "27820007777"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _balance(user_key: str) -> int:
    db = _TestingSession()
    try:
        return get_credit_balance(db, user_key)
    finally:
        db.close()


def _status(m_payment_id: str) -> str:
    db = _TestingSession()
    try:
        return db.query(models.Subscription).filter(
            models.Subscription.m_payment_id == m_payment_id
        ).first().status
    finally:
        db.close()


@pytest.fixture
def _signed(monkeypatch):
    """Force webhook signature verification to pass and configure the secret."""
    monkeypatch.setattr(settings, "YOCO_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(sub_routes, "_verify_yoco_webhook_signature", lambda *a, **k: True)
    monkeypatch.setattr(settings, "FIRST_PURCHASE_BONUS_TOKENS", 0)


def _post(client, ref: str, user_key: str, tokens, amount_cents, event="payment.succeeded"):
    payload = {"id": f"pay_{ref}", "metadata": {"m_payment_id": ref, "user_key": user_key}}
    if tokens is not None:
        payload["metadata"]["tokens"] = tokens
    if amount_cents is not None:
        payload["amount"] = amount_cents
    return client.post(
        "/subscription/webhook",
        content=json.dumps({"type": event, "payload": payload}),
        headers={
            "webhook-id": "wh_1",
            "webhook-timestamp": "1",
            "webhook-signature": "v1,sig",
            "content-type": "application/json",
        },
    )


def _seed_sub(db, user_key, ref, *, status="pending", amount="220.00", **kw):
    sub = models.Subscription(
        user_key=user_key, m_payment_id=ref, status=status, amount=amount, frequency=0, **kw
    )
    db.add(sub)
    db.commit()
    return sub


# ── 1a. Superseded checkouts are parked, not deleted ─────────────────────────

def test_second_checkout_supersedes_instead_of_deleting(monkeypatch):
    """Opening checkout B must leave checkout A on the books, so paying A later
    is still attributable. Deleting it charged the buyer for nothing."""

    class _FakeResp:
        status_code = 200

        def __init__(self, cid):
            self._cid = cid

        def json(self):
            return {"id": self._cid, "redirectUrl": f"https://pay.yoco.test/{self._cid}"}

    created = []

    async def fake_post(*a, **k):
        created.append(k["headers"]["Idempotency-Key"])
        return _FakeResp(f"co_{len(created)}")

    monkeypatch.setattr(settings, "YOCO_SECRET_KEY", "sk_test")
    monkeypatch.setattr(payments._http, "post", fake_post)

    db = _TestingSession()
    try:
        asyncio.run(payments.create_checkout(db, PHONE, 20, channel="whatsapp"))
        asyncio.run(payments.create_checkout(db, PHONE, 5, channel="whatsapp"))

        rows = {s.m_payment_id: s.status for s in
                db.query(models.Subscription).filter_by(user_key=PHONE).all()}
        assert len(rows) == 2, "the earlier checkout must not be deleted"
        assert sorted(rows.values()) == ["pending", "superseded"]
        assert rows[created[0]] == "superseded"
        assert rows[created[1]] == "pending"
    finally:
        db.close()


def test_webhook_credits_a_superseded_checkout(client, _signed):
    """The buyer opened a newer checkout but went back and paid the old one."""
    db = _TestingSession()
    try:
        _seed_sub(db, "admin", "ref-sup", status="superseded", amount="220.00")
    finally:
        db.close()
    start = _balance("admin")

    resp = _post(client, "ref-sup", "admin", tokens=20, amount_cents=22000)

    assert resp.status_code == 200
    assert _balance("admin") == start + 20
    assert _status("ref-sup") == "completed"


def test_superseded_checkout_gets_no_abandonment_reminder(monkeypatch):
    """Only the checkout the buyer is actually looking at earns a nudge."""
    buttons = []

    async def fake_buttons(to, body, btns):
        buttons.append(to)

    monkeypatch.setattr(whatsapp, "_send_whatsapp_buttons", fake_buttons)
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "pnid")
    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(checkout_recovery.flags, "is_enabled", lambda name: True)
    monkeypatch.setattr(checkout_recovery, "record_server_event", lambda *a: None)

    db = _TestingSession()
    try:
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        s1 = _seed_sub(db, PHONE, "co-sup", status="superseded", channel="whatsapp")
        s2 = _seed_sub(db, PHONE, "co-live", status="pending", channel="whatsapp")
        s1.created_at = s2.created_at = old
        db.commit()

        stats = asyncio.run(checkout_recovery.run_checkout_recovery_once(db))
        assert stats["sent"] == 1
        assert buttons == [PHONE]
    finally:
        db.close()


# ── 1b. Webhook metadata fallback ────────────────────────────────────────────

def test_unknown_reference_still_credits_from_metadata(client, _signed, caplog):
    """No checkout row for a succeeded payment: credit from the signed metadata
    and shout about it, rather than 404-ing the money away."""
    start = _balance("orphan@example.com")

    with caplog.at_level("ERROR"):
        resp = _post(client, "ref-orphan", "orphan@example.com", tokens=20, amount_cents=22000)

    assert resp.status_code == 200
    assert _balance("orphan@example.com") == start + 20
    assert _status("ref-orphan") == "completed"
    assert "PAYMENT_RECONCILE" in caplog.text


def test_unknown_reference_without_metadata_is_still_a_404(client, _signed):
    """Nothing to credit and nobody to credit it to — the old behaviour stands."""
    resp = _post(client, "ref-nothing", "", tokens=None, amount_cents=22000)
    assert resp.status_code == 404


def test_amount_mismatch_credits_from_metadata(client, _signed, caplog):
    """A mismatch used to be terminal, which ate the payment."""
    db = _TestingSession()
    try:
        _seed_sub(db, "admin", "ref-mm", amount="220.00")
    finally:
        db.close()
    start = _balance("admin")

    with caplog.at_level("ERROR"):
        resp = _post(client, "ref-mm", "admin", tokens=20, amount_cents=19900)

    assert resp.status_code == 200
    assert _balance("admin") == start + 20
    assert "PAYMENT_RECONCILE" in caplog.text


def test_amount_mismatch_without_metadata_still_rejected(client, _signed):
    db = _TestingSession()
    try:
        _seed_sub(db, "admin", "ref-mm2", amount="220.00")
    finally:
        db.close()

    resp = _post(client, "ref-mm2", "", tokens=None, amount_cents=19900)
    assert resp.status_code == 400
    assert _status("ref-mm2") == "pending"


def test_webhook_timestamp_tolerance_is_five_minutes():
    assert sub_routes.WEBHOOK_MAX_SKEW_SECONDS == 300


# ── 1d. Reconcile sweep ──────────────────────────────────────────────────────

def _patch_reconcile(monkeypatch, yoco_status="completed", tokens=20):
    monkeypatch.setattr(settings, "PAYMENT_RECONCILE_ENABLED", True)
    monkeypatch.setattr(settings, "YOCO_SECRET_KEY", "sk_test")
    monkeypatch.setattr(settings, "FIRST_PURCHASE_BONUS_TOKENS", 0)

    asked: list[str] = []

    async def fake_fetch(checkout_id):
        asked.append(checkout_id)
        return {
            "id": checkout_id,
            "status": yoco_status,
            "paymentId": f"pay_{checkout_id}",
            "metadata": {"tokens": tokens},
        }

    monkeypatch.setattr(payment_reconcile, "_fetch_checkout", fake_fetch)
    return asked


def test_reconcile_sweep_credits_payments_the_webhook_missed(monkeypatch):
    asked = _patch_reconcile(monkeypatch)

    db = _TestingSession()
    try:
        start = get_credit_balance(db, "sweep-user")  # includes the free signup grant
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        pending = _seed_sub(db, "sweep-user", "sw-1", checkout_id="co_1")
        superseded = _seed_sub(db, "sweep-user", "sw-2", status="superseded", checkout_id="co_2")
        stale = _seed_sub(db, "sweep-user", "sw-3", checkout_id="co_3")
        stale.created_at = datetime.now(timezone.utc) - timedelta(hours=72)
        pending.created_at = superseded.created_at = recent
        db.commit()

        stats = asyncio.run(payment_reconcile.run_payment_reconcile_once(db))

        assert stats["credited"] == 2
        assert sorted(asked) == ["co_1", "co_2"]      # the 72h-old row is left alone
        assert get_credit_balance(db, "sweep-user") == start + 40
        assert _status("sw-3") == "pending"

        # Idempotent: a second sweep finds nothing left to credit.
        stats2 = asyncio.run(payment_reconcile.run_payment_reconcile_once(db))
        assert stats2["credited"] == 0
        assert get_credit_balance(db, "sweep-user") == start + 40
    finally:
        db.close()


def test_reconcile_sweep_leaves_unpaid_checkouts_alone(monkeypatch):
    _patch_reconcile(monkeypatch, yoco_status="created")

    db = _TestingSession()
    try:
        start = get_credit_balance(db, "sweep-user-2")
        sub = _seed_sub(db, "sweep-user-2", "sw-10", checkout_id="co_10")
        sub.created_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        db.commit()

        stats = asyncio.run(payment_reconcile.run_payment_reconcile_once(db))

        assert stats["credited"] == 0
        assert stats["still_unpaid"] == 1
        assert get_credit_balance(db, "sweep-user-2") == start
        assert _status("sw-10") == "pending"
    finally:
        db.close()


def test_reconcile_sweep_noops_without_yoco_key(monkeypatch):
    monkeypatch.setattr(settings, "PAYMENT_RECONCILE_ENABLED", True)
    monkeypatch.setattr(settings, "YOCO_SECRET_KEY", "")

    stats = asyncio.run(payment_reconcile.run_payment_reconcile_once())
    assert stats == {"checked": 0, "asked": 0, "credited": 0, "still_unpaid": 0, "errors": 0}


# ── 3. STOP / START opt-out ──────────────────────────────────────────────────

def _patch_inbound(monkeypatch, sent):
    async def fake_send(to, text):
        sent.append(text)

    monkeypatch.setattr(whatsapp, "SessionLocal", _TestingSession)
    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_typing_indicator", lambda *a, **k: _noop())
    monkeypatch.setattr(whatsapp, "_record_whatsapp_message", lambda *a, **k: None)
    monkeypatch.setattr(whatsapp, "feedback_is_eligible", lambda *a, **k: (False, None))


async def _noop():
    return None


def _session_row(phone=PHONE):
    db = _TestingSession()
    try:
        return db.query(models.WhatsAppSession).filter_by(phone_number=phone).first()
    finally:
        db.close()


@pytest.mark.parametrize("word", ["stop", "STOP", " Unsubscribe ", "opt out", "OptOut"])
def test_opt_out_keywords_set_the_flag_and_reply_once(monkeypatch, word):
    sent = []
    _patch_inbound(monkeypatch, sent)

    db = _TestingSession()
    try:
        db.add(models.WhatsAppSession(phone_number=PHONE, mode="chat"))
        db.commit()
    finally:
        db.close()

    asyncio.run(whatsapp._process_whatsapp_message(PHONE, word))

    assert len(sent) == 1
    assert sent[0] == whatsapp._OPT_OUT_REPLY
    assert "won't message you first" in sent[0]
    assert _session_row().opted_out is True


def test_unsubscribe_no_longer_reaches_the_billing_reply(monkeypatch):
    """It used to answer "no recurring plan to cancel" and never opt anyone out."""
    sent = []
    _patch_inbound(monkeypatch, sent)

    db = _TestingSession()
    try:
        db.add(models.WhatsAppSession(phone_number=PHONE, mode="chat"))
        db.commit()
    finally:
        db.close()

    asyncio.run(whatsapp._process_whatsapp_message(PHONE, "unsubscribe"))

    assert "no recurring plan to cancel" not in " ".join(sent)
    assert _session_row().opted_out is True
    assert "unsubscribe" not in whatsapp._GLOBAL_CMDS


def test_start_clears_the_flag_and_confirms(monkeypatch):
    sent = []
    _patch_inbound(monkeypatch, sent)

    db = _TestingSession()
    try:
        db.add(models.WhatsAppSession(
            phone_number=PHONE, mode="chat", opted_out=True,
            opted_out_at=datetime.now(timezone.utc),
        ))
        db.commit()
    finally:
        db.close()

    asyncio.run(whatsapp._process_whatsapp_message(PHONE, " Start "))

    assert len(sent) == 1
    assert sent[0] == whatsapp._OPT_IN_REPLY
    row = _session_row()
    assert row.opted_out is False
    assert row.opted_out_at is None


def test_stop_inside_a_sentence_is_not_an_opt_out(monkeypatch):
    sent = []
    _patch_inbound(monkeypatch, sent)
    monkeypatch.setattr(whatsapp, "_send_help_menu", lambda *a, **k: _noop())

    db = _TestingSession()
    try:
        db.add(models.WhatsAppSession(phone_number=PHONE, mode="chat"))
        db.commit()
    finally:
        db.close()

    asyncio.run(whatsapp._process_whatsapp_message(PHONE, "stop sending me deck jobs please"))

    assert _session_row().opted_out is False


# ── 3. Every proactive loop honours the flag ─────────────────────────────────

def _patch_loops(monkeypatch):
    sends = []

    async def fake_send(to, text):
        sends.append(to)

    async def fake_buttons(to, body, btns):
        sends.append(to)

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_buttons", fake_buttons)
    monkeypatch.setattr(whatsapp, "_wa_configured", lambda: True)
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "pnid")
    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", "tok")
    for mod in (window_winback, apply_followup, job_alerts, checkout_recovery):
        monkeypatch.setattr(mod.flags, "is_enabled", lambda name: True)
        monkeypatch.setattr(mod, "record_server_event", lambda *a: None)
    import app.database as app_database
    monkeypatch.setattr(app_database, "SessionLocal", _TestingSession)
    return sends


def test_window_winback_skips_opted_out_users(monkeypatch):
    sends = _patch_loops(monkeypatch)

    db = _TestingSession()
    try:
        db.add(models.WhatsAppSession(
            phone_number=PHONE, mode="onboarding", opted_out=True,
            partial_profile=json.dumps({"firstName": "Sam"}),
            last_active_at=datetime.now(timezone.utc) - timedelta(hours=4),
        ))
        db.commit()
    finally:
        db.close()

    stats = asyncio.run(window_winback.run_window_winbacks_once())
    assert stats["sent"] == 0
    assert stats["opted_out"] == 1
    assert sends == []


def test_apply_followup_skips_opted_out_users(monkeypatch):
    sends = _patch_loops(monkeypatch)

    db = _TestingSession()
    try:
        now = datetime.now(timezone.utc)
        ms = models.MatchSession(
            user_key=PHONE, status="completed", total_matched=3,
            completed_at=now - timedelta(hours=24),
        )
        db.add(ms)
        db.commit()
        db.add(models.WhatsAppSession(
            phone_number=PHONE, mode="chat", opted_out=True,
            last_match_session_id=ms.id, last_active_at=now - timedelta(hours=1),
        ))
        db.commit()
    finally:
        db.close()

    stats = asyncio.run(apply_followup.run_apply_followups_once())
    assert stats["sent"] == 0
    assert stats["opted_out"] == 1
    assert sends == []


def test_job_alerts_skip_opted_out_users(monkeypatch):
    sends = _patch_loops(monkeypatch)

    db = _TestingSession()
    try:
        now = datetime.now(timezone.utc)
        db.add(models.Job(
            title="Deckhand — 45m MY", role="Deckhand", yacht="MY Test",
            location="Antibes", status="open",
        ))
        db.add(models.CrewProfile(
            user_key=PHONE, profile_slug="abc123", first_name="Sam", desired_role="Deckhand",
        ))
        db.add(models.WhatsAppSession(
            phone_number=PHONE, mode="chat", opted_out=True,
            last_active_at=now - timedelta(hours=1),
        ))
        db.commit()
    finally:
        db.close()

    stats = asyncio.run(job_alerts.run_job_alerts_once())
    assert stats["sent"] == 0
    assert stats["opted_out"] == 1
    assert sends == []


def test_checkout_recovery_skips_opted_out_buyers(monkeypatch):
    sends = _patch_loops(monkeypatch)

    db = _TestingSession()
    try:
        db.add(models.WhatsAppSession(phone_number=PHONE, mode="chat", opted_out=True))
        sub = _seed_sub(db, PHONE, "co-opt", channel="whatsapp",
                        checkout_url="https://pay.yoco.test/co_opt")
        sub.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        db.commit()

        stats = asyncio.run(checkout_recovery.run_checkout_recovery_once(db))
        assert stats["sent"] == 0
        assert sends == []
    finally:
        db.close()


# ── 5/6. Acquisition source + onboarding instrumentation ─────────────────────

def test_source_tag_is_parsed_and_stripped_on_first_contact(monkeypatch):
    sent, events = [], []
    _patch_inbound(monkeypatch, sent)
    monkeypatch.setattr(whatsapp, "record_server_event", lambda *a: events.append(a))

    seen = []

    async def fake_onboarding(wa_session, user_message, db):
        seen.append(user_message)
        return "hi"

    monkeypatch.setattr(whatsapp, "_run_onboarding", fake_onboarding)

    asyncio.run(whatsapp._process_whatsapp_message(PHONE, "match · m-hero"))

    # The tag never reaches the bot…
    assert seen == ["match"]
    # …and is recorded both on the session and as a funnel event.
    assert _session_row().acquisition_source == "m-hero"
    assert (PHONE, "wa_first_contact", "m-hero") in events


def test_untagged_first_contact_is_recorded_as_direct(monkeypatch):
    sent, events = [], []
    _patch_inbound(monkeypatch, sent)
    monkeypatch.setattr(whatsapp, "record_server_event", lambda *a: events.append(a))

    async def fake_onboarding(wa_session, user_message, db):
        return "hi"

    monkeypatch.setattr(whatsapp, "_run_onboarding", fake_onboarding)

    asyncio.run(whatsapp._process_whatsapp_message(PHONE, "hello"))
    asyncio.run(whatsapp._process_whatsapp_message(PHONE, "match · sticky"))

    assert _session_row().acquisition_source == "direct"
    # Only the FIRST message is parsed — a later "· tag" is ordinary text.
    assert [e for e in events if e[1] == "wa_first_contact"] == [
        (PHONE, "wa_first_contact", "direct")
    ]


def test_onboard_field_filled_recorded_once_per_field(monkeypatch):
    events = []
    monkeypatch.setattr(whatsapp, "record_server_event", lambda *a: events.append(a))

    whatsapp._record_onboard_fields(PHONE, {}, {"firstName": "Sam", "_retryCount": 2})
    whatsapp._record_onboard_fields(
        PHONE, {"firstName": "Sam"}, {"firstName": "Sam", "desiredRole": "Deckhand"},
    )

    assert events == [
        (PHONE, "onboard_field_filled", "firstName"),
        (PHONE, "onboard_field_filled", "desiredRole"),
    ]


# ── 4. LLM resilience + stale messages ───────────────────────────────────────

def test_llm_blowup_still_gets_a_reply(monkeypatch):
    """A blown-up handler must say something — the old code dropped the message."""
    sent = []
    _patch_inbound(monkeypatch, sent)

    async def boom(*a, **k):
        raise RuntimeError("openai down")

    monkeypatch.setattr(whatsapp, "_run_onboarding", boom)

    asyncio.run(whatsapp._process_whatsapp_message(PHONE, "hello"))

    assert sent == [whatsapp._GLITCH_REPLY]


def test_call_openai_never_raises(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(whatsapp._http, "post", boom)
    assert asyncio.run(whatsapp._call_openai("sys", [], "hi")) == {}


def test_stale_notice_sent_once_per_burst(monkeypatch):
    monkeypatch.setattr(whatsapp, "_STALE_NOTICE_SENT_AT", {})
    assert whatsapp._should_notify_stale(PHONE) is True
    assert whatsapp._should_notify_stale(PHONE) is False
    assert whatsapp._should_notify_stale("27820009999") is True


def test_stale_message_is_flagged_not_silently_dropped(monkeypatch):
    # Dedup is durable now — keep the claim rows in the test DB.
    monkeypatch.setattr(whatsapp, "SessionLocal", _TestingSession)
    whatsapp._SEEN_MSG_IDS.clear()
    whatsapp._SEEN_MSG_IDS_ORDER.clear()
    old = str(int(datetime.now(timezone.utc).timestamp()) - 3600)
    assert whatsapp._inbound_skip_reason("wamid.stale", old) == "stale"
    fresh = str(int(datetime.now(timezone.utc).timestamp()))
    assert whatsapp._inbound_skip_reason("wamid.fresh", fresh) is None
    assert whatsapp._inbound_skip_reason("wamid.fresh", fresh) == "duplicate"


# ── 2. Payment-link survivability copy ───────────────────────────────────────

def test_checkout_message_carries_the_plain_url_and_no_wallet_promise(monkeypatch):
    ctas = []

    async def fake_cta(to, *, body, button_text, url_link, header=None, footer=None):
        ctas.append(body)

    async def fake_create(db, user_key, tokens, *, channel="web"):
        return "https://pay.yoco.test/co_x"

    monkeypatch.setattr(whatsapp, "_send_whatsapp_cta_url", fake_cta)
    monkeypatch.setattr(whatsapp.payments, "create_checkout", fake_create)
    monkeypatch.setattr(settings, "FIRST_PURCHASE_BONUS_TOKENS", 0)

    db = _TestingSession()
    try:
        asyncio.run(whatsapp._start_whatsapp_checkout(PHONE, 20, db))
    finally:
        db.close()

    assert len(ctas) == 1
    body = ctas[0]
    # The 3-D Secure escape hatch: the raw URL must be tappable in the body.
    assert "https://pay.yoco.test/co_x" in body
    assert "Open in browser" in body
    assert "Pay by card" in body
    # Neither wallet works in WhatsApp's webview — never promise them.
    assert "Apple Pay" not in body and "Google Pay" not in body


def test_checkout_reminder_delay_is_fifteen_minutes():
    assert checkout_recovery.REMIND_AFTER_MINUTES == 15


def test_job_alert_per_run_cap_is_configurable(monkeypatch):
    monkeypatch.setattr(settings, "JOB_ALERT_MAX_PER_RUN", 1)
    sends = _patch_loops(monkeypatch)

    db = _TestingSession()
    try:
        now = datetime.now(timezone.utc)
        db.add(models.Job(
            title="Deckhand — 45m MY", role="Deckhand", yacht="MY Test",
            location="Antibes", status="open",
        ))
        for i, phone in enumerate(("27820001111", "27820002222")):
            db.add(models.CrewProfile(
                user_key=phone, profile_slug=f"slug{i}", first_name="Sam",
                desired_role="Deckhand",
            ))
            db.add(models.WhatsAppSession(
                phone_number=phone, mode="chat", last_active_at=now - timedelta(hours=1),
                # Older than the job, so the job counts as "new to them".
                created_at=now - timedelta(days=2),
            ))
        db.commit()
    finally:
        db.close()

    stats = asyncio.run(job_alerts.run_job_alerts_once())
    assert stats["sent"] == 1
    assert len(sends) == 1
