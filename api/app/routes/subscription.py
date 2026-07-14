import base64
import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models
from app.analytics import record_server_event
from app.database import get_db
from app.logger import get_logger
from app.security import require_session
from app.services import payments
from app.services.credits import add_credits, get_credit_balance
from app.settings import settings

log = get_logger("carver.subscription")

router = APIRouter(prefix="/subscription", tags=["subscription"])

# Back-compat aliases — other modules (and tests) import these from here.
_amount_str_to_cents = payments.amount_str_to_cents
_yoco_configured = payments.yoco_configured
_find_package = payments.find_package
_package_amount = payments.package_amount
_package_for_amount = payments.package_for_amount
_is_first_purchase = payments.is_first_purchase


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
async def create_checkout(body: CheckoutRequest, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    user_key = session.get("sub", "")
    try:
        redirect_url = await payments.create_checkout(db, user_key, body.tokens, channel="web")
    except payments.CheckoutError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"ok": True, "redirect_url": redirect_url}


def _is_whatsapp_user(db: Session, user_key: str) -> bool:
    return (
        db.query(models.WhatsAppSession.phone_number)
        .filter(models.WhatsAppSession.phone_number == user_key)
        .first()
    ) is not None


async def _notify_whatsapp_purchase(user_key: str, tokens_added: int, bonus: int, balance: int) -> None:
    """Confirm a completed purchase in the buyer's WhatsApp chat. Best-effort."""
    try:
        from app.routes.whatsapp import _send_whatsapp, _send_whatsapp_buttons

        bonus_line = f"🎁 Includes your *+{bonus}* first-purchase bonus.\n" if bonus > 0 else ""
        await _send_whatsapp(
            user_key,
            f"✅ *Payment received — {tokens_added} tokens added!*\n"
            f"{bonus_line}"
            f"💳 New balance: *{balance}* token{'s' if balance != 1 else ''}.\n\n"
            "Ready when you are — run *Find Matches* to put them to work. 🛥️",
        )
        await _send_whatsapp_buttons(
            user_key,
            "What's next?",
            [("btn_find_matches", "Find Matches"), ("btn_menu", "Menu")],
        )
    except Exception:
        log.exception("WhatsApp purchase confirmation failed | user=%s", user_key)


async def _notify_whatsapp_payment_failed(user_key: str) -> None:
    """Tell a WhatsApp buyer their payment failed so they can retry. Best-effort."""
    try:
        from app.routes.whatsapp import _send_whatsapp_buttons

        await _send_whatsapp_buttons(
            user_key,
            "⚠️ Your payment didn't go through — you were *not* charged.\n\nWant to try again?",
            [("cmd_subscribe", "Buy Tokens"), ("btn_menu", "Menu")],
        )
    except Exception:
        log.exception("WhatsApp payment-failed notice failed | user=%s", user_key)


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

    from_whatsapp = meta.get("channel") == "whatsapp" or _is_whatsapp_user(db, sub.user_key)

    if event_type == "payment.succeeded":
        if sub.status == "completed":
            # Yoco delivers webhooks at-least-once, so the same payment.succeeded
            # can arrive more than once. Tokens were already credited on the
            # first delivery — ignore duplicates to avoid double-crediting.
            log.info("Yoco webhook duplicate succeeded ignored | user=%s | ref=%s", sub.user_key, m_payment_id)
            return {"ok": True}
        amount_cents = payload.get("amount")
        if amount_cents is not None:
            expected = _amount_str_to_cents(sub.amount)
            try:
                if int(amount_cents) != expected:
                    log.warning("Yoco webhook amount mismatch | expected=%s | got=%s", expected, amount_cents)
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount mismatch")
            except (TypeError, ValueError):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount mismatch")

        first_purchase = _is_first_purchase(db, sub.user_key, exclude_payment_id=sub.m_payment_id)

        sub.status = "completed"
        if payload.get("id"):
            sub.payment_token = str(payload["id"])
        db.commit()

        tokens_credited = 0
        tokens_to_add = meta.get("tokens")
        if tokens_to_add and int(tokens_to_add) > 0:
            tokens_credited = int(tokens_to_add)
            add_credits(db, sub.user_key, tokens_credited)
            log.info("Tokens credited | user=%s | tokens=%d", sub.user_key, tokens_credited)
        else:
            fallback_pkg = _package_for_amount(_amount_str_to_cents(sub.amount))
            if fallback_pkg is not None:
                tokens_credited = int(fallback_pkg["tokens"])
                add_credits(db, sub.user_key, tokens_credited)
                log.info("Tokens credited (from amount) | user=%s | tokens=%d", sub.user_key, tokens_credited)
            else:
                log.warning("Could not resolve token count for completed payment | user=%s | amount=%s", sub.user_key, sub.amount)

        bonus_credited = 0
        bonus = settings.FIRST_PURCHASE_BONUS_TOKENS
        bonus_eligible = tokens_credited >= settings.FIRST_PURCHASE_BONUS_MIN_TOKENS
        if first_purchase and bonus > 0 and bonus_eligible:
            bonus_credited = bonus
            add_credits(db, sub.user_key, bonus)
            log.info("First-purchase bonus credited | user=%s | bonus=%d", sub.user_key, bonus)

        log.info("Token purchase completed | user=%s", sub.user_key)
        record_server_event(sub.user_key, "purchase_completed", str(sub.amount))

        if from_whatsapp and tokens_credited > 0:
            await _notify_whatsapp_purchase(
                sub.user_key,
                tokens_credited + bonus_credited,
                bonus_credited,
                get_credit_balance(db, sub.user_key),
            )
    elif event_type == "payment.failed":
        sub.status = "failed"
        log.warning("Token purchase payment failed | user=%s", sub.user_key)
        db.commit()
        if from_whatsapp:
            await _notify_whatsapp_payment_failed(sub.user_key)
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
        if not p.get("wa_only")
    ]
    bonus = settings.FIRST_PURCHASE_BONUS_TOKENS
    return {
        "ok": True,
        "balance": balance,
        "token_price": token_price,
        "packages": packages,
        "first_purchase_bonus": bonus if (bonus > 0 and _is_first_purchase(db, user_key)) else 0,
    }
