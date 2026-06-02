import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.logger import get_logger
from app.security import require_session
from app.services.credits import add_credits, get_credit_balance
from app.settings import settings

log = get_logger("carver.subscription")

router = APIRouter(prefix="/subscription", tags=["subscription"])

YOCO_CHECKOUTS_URL = "https://payments.yoco.com/api/checkouts"


def _amount_str_to_cents(amount_str: str) -> int:
    return int(round(float(amount_str.strip()) * 100))


def _yoco_configured() -> bool:
    return bool(settings.YOCO_SECRET_KEY)


def _find_package(tokens: int) -> dict | None:
    """Return the configured pack matching this token count, if any."""
    for pkg in settings.TOKEN_PACKAGES:
        if int(pkg["tokens"]) == tokens:
            return pkg
    return None


def _package_amount(tokens: int) -> int:
    """Return the total price in cents for a token package."""
    pkg = _find_package(tokens)
    if pkg is None:
        raise ValueError(f"Unknown token package: {tokens}")
    return _amount_str_to_cents(pkg["price"])


def _package_for_amount(cents: int) -> dict | None:
    """Reverse-lookup a pack from a charged amount (webhook fallback)."""
    for pkg in settings.TOKEN_PACKAGES:
        if _amount_str_to_cents(pkg["price"]) == cents:
            return pkg
    return None


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


class CheckoutRequest(BaseModel):
    tokens: int


@router.post("/checkout")
def create_checkout(body: CheckoutRequest, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    if not _yoco_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment provider is not configured yet.",
        )

    pkg = _find_package(body.tokens)
    if pkg is None:
        valid = [p["tokens"] for p in settings.TOKEN_PACKAGES]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid package. Choose one of: {valid}",
        )

    user_key = session.get("sub", "")
    payment_id = uuid.uuid4().hex
    cents = _package_amount(body.tokens)
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

    frontend_base = settings.FRONTEND_BASE_URL.rstrip("/")

    payload: dict[str, Any] = {
        "amount": cents,
        "currency": "ZAR",
        "successUrl": f"{frontend_base}/subscription?status=success",
        "cancelUrl": f"{frontend_base}/subscription?status=cancelled",
        "failureUrl": f"{frontend_base}/subscription?status=failed",
        "clientReferenceId": payment_id,
        "metadata": {"m_payment_id": payment_id, "user_key": user_key, "tokens": body.tokens},
        "lineItems": [
            {
                "displayName": f"CARVER {pkg['label']} Pack",
                "description": f"{body.tokens} tokens for R{pkg['price']}",
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

    if data.get("id"):
        sub.checkout_id = str(data["id"])
        db.commit()

    log.info("Checkout created | user=%s | payment_id=%s | tokens=%d | checkout_id=%s", user_key, payment_id, body.tokens, data.get("id"))
    return {"ok": True, "redirect_url": redirect_url}


@router.post("/webhook")
async def yoco_webhook(request: Request, db: Session = Depends(get_db)):
    """Yoco payment webhooks — verify signature, then credit tokens."""
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

        sub.status = "completed"
        if payload.get("id"):
            sub.payment_token = str(payload["id"])
        db.commit()

        tokens_to_add = meta.get("tokens")
        if tokens_to_add and int(tokens_to_add) > 0:
            add_credits(db, sub.user_key, int(tokens_to_add))
            log.info("Tokens credited | user=%s | tokens=%d", sub.user_key, int(tokens_to_add))
        else:
            fallback_pkg = _package_for_amount(_amount_str_to_cents(sub.amount))
            if fallback_pkg is not None:
                add_credits(db, sub.user_key, int(fallback_pkg["tokens"]))
                log.info("Tokens credited (from amount) | user=%s | tokens=%d", sub.user_key, int(fallback_pkg["tokens"]))
            else:
                log.warning("Could not resolve token count for completed payment | user=%s | amount=%s", sub.user_key, sub.amount)

        log.info("Token purchase completed | user=%s", sub.user_key)
    elif event_type == "payment.failed":
        sub.status = "failed"
        log.warning("Token purchase payment failed | user=%s", sub.user_key)
        db.commit()
    else:
        log.info("Yoco webhook ignored event type | type=%s", event_type)

    return {"ok": True}


@router.get("/status")
def subscription_status(session: dict = Depends(require_session), db: Session = Depends(get_db)):
    user_key = session.get("sub", "")
    balance = get_credit_balance(db, user_key)
    token_price = settings.TOKEN_PRICE
    packages = [
        {
            "tokens": int(p["tokens"]),
            "price": p["price"],
            "label": p.get("label", f"{p['tokens']} Token Pack"),
            "badge": p.get("badge"),
            "highlight": bool(p.get("highlight", False)),
            "price_per_token": f"{(float(p['price']) / int(p['tokens'])):.2f}",
        }
        for p in settings.TOKEN_PACKAGES
    ]
    return {
        "ok": True,
        "balance": balance,
        "token_price": token_price,
        "packages": packages,
    }
