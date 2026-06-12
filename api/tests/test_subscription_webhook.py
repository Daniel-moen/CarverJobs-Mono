"""Yoco webhook crediting — happy path + idempotency (no double-credit)."""
import json

import pytest

from app import models
from app.routes import subscription as sub_routes
from app.services.credits import get_credit_balance
from app.settings import settings
from tests.conftest import _TestingSession


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


def _balance(user_key: str) -> int:
    db = _TestingSession()
    try:
        return get_credit_balance(db, user_key)
    finally:
        db.close()


def _sub_status(m_payment_id: str) -> str:
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


def _post(client, ref: str, tokens: int, amount_cents: int):
    event = {
        "type": "payment.succeeded",
        "payload": {
            "id": "pay_123",
            "amount": amount_cents,
            "metadata": {"m_payment_id": ref, "user_key": "admin", "tokens": tokens},
        },
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


def test_webhook_credits_once_then_is_idempotent(client, _signed, monkeypatch):
    monkeypatch.setattr(settings, "FIRST_PURCHASE_BONUS_TOKENS", 0)
    _seed_pending("admin", "ref-1", "220.00")
    start = _balance("admin")

    first = _post(client, "ref-1", tokens=20, amount_cents=22000)
    assert first.status_code == 200
    assert _balance("admin") == start + 20
    assert _sub_status("ref-1") == "completed"

    # Duplicate delivery of the same succeeded event must NOT credit again.
    second = _post(client, "ref-1", tokens=20, amount_cents=22000)
    assert second.status_code == 200
    assert _balance("admin") == start + 20


def test_first_purchase_bonus_applied_once(client, _signed, monkeypatch):
    monkeypatch.setattr(settings, "FIRST_PURCHASE_BONUS_TOKENS", 5)
    _seed_pending("admin", "ref-b1", "220.00")
    start = _balance("admin")

    # First completed purchase gets the pack plus the bonus.
    first = _post(client, "ref-b1", tokens=20, amount_cents=22000)
    assert first.status_code == 200
    assert _balance("admin") == start + 20 + 5

    # Duplicate delivery must not re-apply the bonus either.
    dup = _post(client, "ref-b1", tokens=20, amount_cents=22000)
    assert dup.status_code == 200
    assert _balance("admin") == start + 20 + 5

    # A second, distinct purchase gets no bonus.
    _seed_pending("admin", "ref-b2", "65.00")
    second = _post(client, "ref-b2", tokens=5, amount_cents=6500)
    assert second.status_code == 200
    assert _balance("admin") == start + 20 + 5 + 5  # +5 pack tokens, no bonus
