"""In-chat WhatsApp token purchase + webhook purchase confirmation."""
import asyncio
import json

import pytest

from app import models
from app.routes import subscription as sub_routes
from app.routes import whatsapp
from app.services import payments
from app.services.credits import get_credit_balance
from app.settings import settings
from tests.conftest import _TestingSession


PHONE = "27820001111"


# ── WhatsApp chat flow ─────────────────────────────────────────────────────────


class _FakeWaSession:
    phone_number = PHONE
    mode = "chat"


def _patch_chat(monkeypatch, sent, lists):
    async def fake_send(to, text):
        sent.append(text)

    async def fake_buttons(to, body, buttons):
        sent.append(body)

    async def fake_list(to, **kwargs):
        lists.append(kwargs)

    async def fake_cta(to, **kwargs):
        # Body and URL land in `sent` so link/copy assertions cover CTA messages too.
        sent.append(f"{kwargs.get('body', '')} {kwargs.get('url_link', '')}".strip())

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_buttons", fake_buttons)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_list", fake_list)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_cta_url", fake_cta)
    monkeypatch.setattr(whatsapp, "get_credit_balance", lambda db, key: 3)
    monkeypatch.setattr(whatsapp, "_is_first_purchase", lambda db, key: True)
    monkeypatch.setattr(whatsapp, "_record_whatsapp_message", lambda *a, **k: None)


def test_buy_tokens_sends_pack_picker(monkeypatch):
    sent, lists = [], []
    _patch_chat(monkeypatch, sent, lists)
    monkeypatch.setattr(payments, "yoco_configured", lambda: True)

    db = _TestingSession()
    try:
        asyncio.run(whatsapp._run_chat(_FakeWaSession(), "buy tokens", db))
    finally:
        db.close()

    assert len(lists) == 1
    rows = lists[0]["rows"]
    expected_ids = {f"buy_{int(p['tokens'])}" for p in settings.TOKEN_PACKAGES}
    assert {r["id"] for r in rows} == expected_ids
    # First-purchase bonus is advertised to eligible users.
    assert "bonus" in lists[0]["body"].lower()


def test_buy_tokens_falls_back_to_magic_link_without_yoco(monkeypatch):
    sent, lists = [], []
    _patch_chat(monkeypatch, sent, lists)
    monkeypatch.setattr(payments, "yoco_configured", lambda: False)
    monkeypatch.setattr(whatsapp, "_make_magic_link", lambda phone, db, redirect_to=None: "https://x/wa/tok")

    db = _TestingSession()
    try:
        asyncio.run(whatsapp._run_chat(_FakeWaSession(), "buy tokens", db))
    finally:
        db.close()

    assert not lists
    assert any("https://x/wa/tok" in t for t in sent)


def test_buy_pack_sends_direct_payment_link(monkeypatch):
    sent, lists = [], []
    _patch_chat(monkeypatch, sent, lists)
    captured = {}

    async def fake_checkout(db, user_key, tokens, *, channel="web"):
        captured["user_key"] = user_key
        captured["tokens"] = tokens
        captured["channel"] = channel
        return "https://pay.yoco.test/co_123"

    monkeypatch.setattr(payments, "create_checkout", fake_checkout)

    db = _TestingSession()
    try:
        asyncio.run(whatsapp._run_chat(_FakeWaSession(), "buy pack 20", db))
    finally:
        db.close()

    assert captured == {"user_key": PHONE, "tokens": 20, "channel": "whatsapp"}
    assert any("https://pay.yoco.test/co_123" in t for t in sent)


def test_buy_pack_unknown_size_reshows_picker(monkeypatch):
    sent, lists = [], []
    _patch_chat(monkeypatch, sent, lists)
    monkeypatch.setattr(payments, "yoco_configured", lambda: True)

    db = _TestingSession()
    try:
        asyncio.run(whatsapp._run_chat(_FakeWaSession(), "buy pack 999", db))
    finally:
        db.close()

    assert len(lists) == 1  # picker re-sent, no checkout attempted


def test_buy_pack_checkout_error_falls_back_to_web_link(monkeypatch):
    sent, lists = [], []
    _patch_chat(monkeypatch, sent, lists)

    async def failing_checkout(db, user_key, tokens, *, channel="web"):
        raise payments.CheckoutError("Payment provider unreachable. Please try again.")

    monkeypatch.setattr(payments, "create_checkout", failing_checkout)
    monkeypatch.setattr(whatsapp, "_make_magic_link", lambda phone, db, redirect_to=None: "https://x/wa/tok")

    db = _TestingSession()
    try:
        asyncio.run(whatsapp._run_chat(_FakeWaSession(), "buy pack 20", db))
    finally:
        db.close()

    assert any("https://x/wa/tok" in t for t in sent)


def test_feedback_request_does_not_promise_disabled_reward(monkeypatch):
    sent, lists = [], []
    _patch_chat(monkeypatch, sent, lists)
    monkeypatch.setattr(whatsapp, "_make_magic_link", lambda phone, db, redirect_to=None: "https://x/wa/tok")
    monkeypatch.setattr(whatsapp, "FEEDBACK_REWARD_TOKENS", 0)

    db = _TestingSession()
    try:
        asyncio.run(whatsapp._send_feedback_request(PHONE, db))
    finally:
        db.close()

    assert len(sent) == 1
    assert "token" not in sent[0].lower()


# ── Webhook → WhatsApp confirmation ───────────────────────────────────────────


@pytest.fixture
def _signed(monkeypatch):
    monkeypatch.setattr(settings, "YOCO_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(sub_routes, "_verify_yoco_webhook_signature", lambda *a, **k: True)


def _seed_pending(user_key: str, m_payment_id: str, amount: str) -> None:
    db = _TestingSession()
    try:
        db.add(models.Subscription(
            user_key=user_key,
            m_payment_id=m_payment_id,
            status="pending",
            amount=amount,
            frequency=0,
        ))
        db.commit()
    finally:
        db.close()


def _post_webhook(client, ref: str, tokens: int, amount_cents: int, channel: str | None):
    metadata = {"m_payment_id": ref, "user_key": PHONE, "tokens": tokens}
    if channel:
        metadata["channel"] = channel
    event = {
        "type": "payment.succeeded",
        "payload": {"id": "pay_wa1", "amount": amount_cents, "metadata": metadata},
    }
    return client.post(
        "/subscription/webhook",
        content=json.dumps(event),
        headers={
            "webhook-id": "wh_1",
            "webhook-timestamp": "1",
            "webhook-signature": "v1,sig",
            "content-type": "application/json",
        },
    )


def test_whatsapp_channel_purchase_sends_chat_confirmation(client, _signed, monkeypatch):
    monkeypatch.setattr(settings, "FIRST_PURCHASE_BONUS_TOKENS", 5)
    _seed_pending(PHONE, "ref-wa-1", "220.00")
    notified = {}

    async def fake_notify(user_key, tokens_added, bonus, balance):
        notified.update(user_key=user_key, tokens_added=tokens_added, bonus=bonus, balance=balance)

    monkeypatch.setattr(sub_routes, "_notify_whatsapp_purchase", fake_notify)

    resp = _post_webhook(client, "ref-wa-1", tokens=20, amount_cents=22000, channel="whatsapp")
    assert resp.status_code == 200
    assert notified["user_key"] == PHONE
    assert notified["tokens_added"] == 25  # 20 pack + 5 first-purchase bonus
    assert notified["bonus"] == 5

    db = _TestingSession()
    try:
        assert notified["balance"] == get_credit_balance(db, PHONE)
    finally:
        db.close()


def test_web_purchase_does_not_send_chat_confirmation(client, _signed, monkeypatch):
    monkeypatch.setattr(settings, "FIRST_PURCHASE_BONUS_TOKENS", 0)
    _seed_pending("someone@example.com", "ref-web-1", "220.00")
    called = []

    async def fake_notify(*a, **k):
        called.append(a)

    monkeypatch.setattr(sub_routes, "_notify_whatsapp_purchase", fake_notify)

    metadata = {"m_payment_id": "ref-web-1", "user_key": "someone@example.com", "tokens": 20, "channel": "web"}
    event = {"type": "payment.succeeded", "payload": {"id": "pay_w1", "amount": 22000, "metadata": metadata}}
    resp = client.post(
        "/subscription/webhook",
        content=json.dumps(event),
        headers={
            "webhook-id": "wh_1",
            "webhook-timestamp": "1",
            "webhook-signature": "v1,sig",
            "content-type": "application/json",
        },
    )
    assert resp.status_code == 200
    assert not called
