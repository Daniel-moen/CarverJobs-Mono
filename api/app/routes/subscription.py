import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.logger import get_logger
from app.security import require_session
from app.settings import settings

log = get_logger("carver.subscription")

router = APIRouter(prefix="/subscription", tags=["subscription"])

YOCO_CHECKOUTS_URL = "https://payments.yoco.com/api/checkouts"


def _amount_str_to_cents(amount_str: str) -> int:
    return int(round(float(amount_str.strip()) * 100))


def _yoco_configured() -> bool:
    return bool(settings.YOCO_SECRET_KEY)


def _verify_yoco_webhook_signature(
    raw_body: bytes,
    webhook_id: str | None,
    webhook_timestamp: str | None,
    signature_header: str | None,
    secret: str,
) -> bool:
    """Verify Yoco webhook per https://developer.yoco.com/guides/online-payments/webhooks/verifying-the-events"""
    if not webhook_id or not webhook_timestamp or not signature_header:
        return False
    try:
        ts = int(webhook_timestamp)
    except (TypeError, ValueError):
        return False
    if abs(int(time.time()) - ts) > 180:
        return False
    if not secret.startswith("whsec_"):
        return False
    try:
        secret_bytes = base64.b64decode(secret.split("_", 1)[1])
    except (IndexError, ValueError):
        return False
    signed_content = f"{webhook_id}.{webhook_timestamp}.{raw_body.decode('utf-8')}"
    expected = base64.b64encode(
        hmac.new(secret_bytes, signed_content.encode("utf-8"), hashlib.sha256).digest()
    ).decode()
    for part in signature_header.split():
        if "," not in part:
            continue
        _, sig = part.split(",", 1)
        if hmac.compare_digest(sig.strip(), expected):
            return True
    return False


@router.post("/checkout")
def create_checkout(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    if not _yoco_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment provider is not configured yet.",
        )

    user_key = session.get("sub", "")
    payment_id = uuid.uuid4().hex

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
        amount=settings.YOCO_MONTHLY_AMOUNT,
        frequency=3,
    )
    db.add(sub)
    db.commit()

    frontend_base = settings.FRONTEND_BASE_URL.rstrip("/")
    cents = _amount_str_to_cents(settings.YOCO_MONTHLY_AMOUNT)

    payload: dict[str, Any] = {
        "amount": cents,
        "currency": "ZAR",
        "successUrl": f"{frontend_base}/subscription?status=success",
        "cancelUrl": f"{frontend_base}/subscription?status=cancelled",
        "failureUrl": f"{frontend_base}/subscription?status=failed",
        "clientReferenceId": payment_id,
        "metadata": {"m_payment_id": payment_id, "user_key": user_key},
        "lineItems": [
            {
                "displayName": "CARVER Pro Monthly",
                "description": "CARVER Pro — monthly access",
                "quantity": 1,
                "pricingDetails": {"price": cents},
            }
        ],
    }

    try:
        resp = httpx.post(
            YOCO_CHECKOUTS_URL,
            headers={
                "Authorization": f"Bearer {settings.YOCO_SECRET_KEY}",
                "Content-Type": "application/json",
                "Idempotency-Key": payment_id,
            },
            json=payload,
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        log.exception("Yoco checkout request failed | user=%s", user_key)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Payment provider unreachable. Please try again.",
        ) from exc

    if resp.status_code != 200:
        yoco_body = resp.text[:500]
        try:
            yoco_err = resp.json()
            yoco_detail = yoco_err.get("detail") or yoco_err.get("message") or yoco_body
        except Exception:
            yoco_detail = yoco_body
        log.warning(
            "Yoco checkout rejected | status=%s | detail=%s",
            resp.status_code,
            yoco_detail,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start checkout. Please try again.",
        )

    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        log.warning("Yoco checkout invalid JSON | %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid response from payment provider.",
        ) from exc

    redirect_url = data.get("redirectUrl")
    if not redirect_url:
        log.warning("Yoco checkout missing redirectUrl | keys=%s", list(data.keys()))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid response from payment provider.",
        )

    # Persist the Yoco checkout session id for auditing / future refund lookups.
    if data.get("id"):
        sub.checkout_id = str(data["id"])
        db.commit()

    log.info("Checkout created | user=%s | payment_id=%s | checkout_id=%s", user_key, payment_id, data.get("id"))
    return {"ok": True, "redirect_url": redirect_url}


@router.post("/webhook")
async def yoco_webhook(request: Request, db: Session = Depends(get_db)):
    """Yoco payment webhooks — verify signature, then update subscription."""
    raw = await request.body()
    wh_id = request.headers.get("webhook-id")
    wh_ts = request.headers.get("webhook-timestamp")
    wh_sig = request.headers.get("webhook-signature")

    if not settings.YOCO_WEBHOOK_SECRET:
        log.error("YOCO_WEBHOOK_SECRET not configured")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook not configured")

    if not _verify_yoco_webhook_signature(raw, wh_id, wh_ts, wh_sig, settings.YOCO_WEBHOOK_SECRET):
        log.warning("Yoco webhook rejected: invalid signature")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")

    try:
        event = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    event_type = event.get("type")
    payload = event.get("payload") or {}
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    m_payment_id = meta.get("m_payment_id")
    if not m_payment_id:
        log.warning("Yoco webhook missing m_payment_id")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing reference")

    sub = db.query(models.Subscription).filter(models.Subscription.m_payment_id == str(m_payment_id)).first()
    if not sub:
        log.warning("Yoco webhook unknown m_payment_id=%s", m_payment_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")

    if event_type == "payment.succeeded":
        amount_cents = payload.get("amount")
        if amount_cents is not None:
            expected = _amount_str_to_cents(sub.amount)
            try:
                if int(amount_cents) != expected:
                    log.warning("Yoco webhook amount mismatch | expected=%s | got=%s", expected, amount_cents)
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount mismatch")
            except (TypeError, ValueError):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount mismatch")

        sub.status = "active"
        if payload.get("id"):
            sub.payment_token = str(payload["id"])
        sub.next_billing_date = (
            datetime.now(timezone.utc) + timedelta(days=30)
        ).strftime("%Y-%m-%d")
        user = db.query(models.User).filter(models.User.email == sub.user_key).first()
        if user:
            user.is_subscribed = True
        log.info("Subscription activated | user=%s | next_billing=%s", sub.user_key, sub.next_billing_date)
        db.commit()
    elif event_type == "payment.failed":
        sub.status = "failed"
        log.warning("Subscription payment failed | user=%s", sub.user_key)
        db.commit()
    else:
        log.info("Yoco webhook ignored event type | type=%s", event_type)

    return {"ok": True}


@router.post("/cancel")
def cancel_subscription(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    user_key = session.get("sub", "")
    sub = (
        db.query(models.Subscription)
        .filter(models.Subscription.user_key == user_key, models.Subscription.status == "active")
        .first()
    )
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active subscription found.")

    sub.status = "cancelled"
    user = db.query(models.User).filter(models.User.email == user_key).first()
    if user:
        user.is_subscribed = False
    db.commit()

    log.info("Subscription cancelled by user | user=%s", user_key)
    return {"ok": True, "detail": "Subscription cancelled."}


@router.get("/status")
def subscription_status(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    user_key = session.get("sub", "")
    monthly_amount = settings.YOCO_MONTHLY_AMOUNT
    free_tokens = settings.FREE_MONTHLY_TOKENS
    sub = (
        db.query(models.Subscription)
        .filter(models.Subscription.user_key == user_key, models.Subscription.status == "active")
        .first()
    )
    if not sub:
        return {"ok": True, "subscribed": False, "monthly_amount": monthly_amount, "free_monthly_tokens": free_tokens}
    return {
        "ok": True,
        "subscribed": True,
        "next_billing_date": sub.next_billing_date,
        "amount": sub.amount,
        "monthly_amount": monthly_amount,
        "free_monthly_tokens": free_tokens,
    }
