"""Yoco checkout creation, shared by the web route and the WhatsApp buy flow.

The web flow (`routes/subscription.py`) and the in-chat WhatsApp flow
(`routes/whatsapp.py`) both create the same Yoco checkout; only the
post-payment redirect differs per channel. Crediting always happens in the
Yoco webhook (`routes/subscription.py`), never here.
"""
from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app import models
from app.analytics import record_server_event
from app.logger import get_logger
from app.settings import settings

log = get_logger("carver.payments")

YOCO_CHECKOUTS_URL = "https://payments.yoco.com/api/checkouts"

_http = httpx.AsyncClient(timeout=30.0)


class CheckoutError(Exception):
    """User-presentable checkout failure."""

    def __init__(self, detail: str, status_code: int = 502):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def amount_str_to_cents(amount_str: str) -> int:
    return int(round(float(amount_str.strip()) * 100))


def yoco_configured() -> bool:
    return bool(settings.YOCO_SECRET_KEY)


def find_package(tokens: int) -> dict | None:
    """Return the configured pack matching this token count, if any."""
    for pkg in settings.TOKEN_PACKAGES:
        if int(pkg["tokens"]) == tokens:
            return pkg
    return None


def package_amount(tokens: int) -> int:
    """Return the total price in cents for a token package."""
    pkg = find_package(tokens)
    if pkg is None:
        raise ValueError(f"Unknown token package: {tokens}")
    return amount_str_to_cents(pkg["price"])


def package_for_amount(cents: int) -> dict | None:
    """Reverse-lookup a pack from a charged amount (webhook fallback)."""
    for pkg in settings.TOKEN_PACKAGES:
        if amount_str_to_cents(pkg["price"]) == cents:
            return pkg
    return None


def is_first_purchase(db: Session, user_key: str, exclude_payment_id: str | None = None) -> bool:
    """True if the user has no completed purchase other than the one being processed."""
    q = db.query(models.Subscription).filter(
        models.Subscription.user_key == user_key,
        models.Subscription.status == "completed",
    )
    if exclude_payment_id:
        q = q.filter(models.Subscription.m_payment_id != exclude_payment_id)
    return q.first() is None


def _redirect_urls(channel: str) -> dict[str, str]:
    """Per-channel post-payment browser redirects.

    WhatsApp buyers should land back in the chat (the webhook confirms the
    purchase there); web buyers return to the subscription page, which polls
    for the credited balance.
    """
    frontend_base = settings.FRONTEND_BASE_URL.rstrip("/")
    web = {
        "successUrl": f"{frontend_base}/subscription?status=success",
        "cancelUrl": f"{frontend_base}/subscription?status=cancelled",
        "failureUrl": f"{frontend_base}/subscription?status=failed",
    }
    if channel == "whatsapp" and settings.WHATSAPP_PUBLIC_NUMBER:
        back_to_chat = f"https://wa.me/{settings.WHATSAPP_PUBLIC_NUMBER}"
        return {"successUrl": back_to_chat, "cancelUrl": back_to_chat, "failureUrl": back_to_chat}
    return web


async def create_checkout(db: Session, user_key: str, tokens: int, *, channel: str = "web") -> str:
    """Create a Yoco checkout for a token pack and return the payment URL.

    Raises CheckoutError with a user-presentable message on any failure.
    """
    if not yoco_configured():
        raise CheckoutError("Payment provider is not configured yet.", status_code=503)

    pkg = find_package(tokens)
    if pkg is None:
        valid = [p["tokens"] for p in settings.TOKEN_PACKAGES]
        raise CheckoutError(f"Invalid package. Choose one of: {valid}", status_code=400)

    payment_id = uuid.uuid4().hex
    cents = package_amount(tokens)
    amount_str = f"{cents / 100:.2f}"

    existing = (
        db.query(models.Subscription)
        .filter(models.Subscription.user_key == user_key, models.Subscription.status == "pending")
        .first()
    )
    if existing:
        db.delete(existing)
        db.flush()

    sub = models.Subscription(
        user_key=user_key,
        m_payment_id=payment_id,
        status="pending",
        amount=amount_str,
        frequency=0,
    )
    db.add(sub)
    db.commit()

    payload: dict[str, Any] = {
        "amount": cents,
        "currency": "ZAR",
        **_redirect_urls(channel),
        "clientReferenceId": payment_id,
        "metadata": {
            "m_payment_id": payment_id,
            "user_key": user_key,
            "tokens": tokens,
            "channel": channel,
        },
        "lineItems": [
            {
                "displayName": f"CARVER {pkg['label']} Pack",
                "description": f"{tokens} tokens for R{pkg['price']}",
                "quantity": 1,
                "pricingDetails": {"price": cents},
            }
        ],
    }

    try:
        resp = await _http.post(
            YOCO_CHECKOUTS_URL,
            headers={
                "Authorization": f"Bearer {settings.YOCO_SECRET_KEY}",
                "Content-Type": "application/json",
                "Idempotency-Key": payment_id,
            },
            json=payload,
        )
    except httpx.HTTPError as exc:
        log.exception("Yoco checkout request failed | user=%s", user_key)
        raise CheckoutError("Payment provider unreachable. Please try again.") from exc

    if resp.status_code != 200:
        yoco_body = resp.text[:500]
        try:
            yoco_err = resp.json()
            yoco_detail = yoco_err.get("detail") or yoco_err.get("message") or yoco_body
        except Exception:
            yoco_detail = yoco_body
        log.warning("Yoco checkout rejected | status=%s | detail=%s", resp.status_code, yoco_detail)
        raise CheckoutError("Could not start checkout. Please try again.")

    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        log.warning("Yoco checkout invalid JSON | %s", exc)
        raise CheckoutError("Invalid response from payment provider.") from exc

    redirect_url = data.get("redirectUrl")
    if not redirect_url:
        log.warning("Yoco checkout missing redirectUrl | keys=%s", list(data.keys()))
        raise CheckoutError("Invalid response from payment provider.")

    if data.get("id"):
        sub.checkout_id = str(data["id"])
        db.commit()

    record_server_event(user_key, "checkout_started", f"{channel}:{tokens}")
    log.info(
        "Checkout created | user=%s | payment_id=%s | tokens=%d | channel=%s | checkout_id=%s",
        user_key, payment_id, tokens, channel, data.get("id"),
    )
    return redirect_url
