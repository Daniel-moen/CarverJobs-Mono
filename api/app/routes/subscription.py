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

# How far a webhook timestamp may drift from our clock before we reject it as a
# replay. Yoco retries deliveries and our clock is not theirs — 180s was tight
# enough that legitimate retries were being thrown away (and the payment lost).
WEBHOOK_MAX_SKEW_SECONDS = 300

# Checkout rows that have been paid for but not yet credited. "superseded" is a
# checkout the buyer abandoned in favour of a newer one and then paid anyway
# (see services/payments.create_checkout) — it credits exactly like "pending".
CREDITABLE_STATUSES = ("pending", "superseded")


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
    if abs(int(time.time()) - ts) > WEBHOOK_MAX_SKEW_SECONDS:
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


async def credit_successful_payment(
    db: Session,
    sub: models.Subscription,
    *,
    tokens_hint: int | None = None,
    payment_id: str | None = None,
    source: str = "webhook",
    from_whatsapp: bool | None = None,
) -> dict:
    """Credit a paid checkout exactly once, tokens + first-purchase bonus.

    The single crediting path: the Yoco webhook calls it on payment.succeeded,
    and the reconcile sweep (services/payment_reconcile.py) calls it for
    payments whose webhook never arrived. Idempotent — a row already marked
    "completed" is a no-op, so a webhook racing the sweep cannot double-credit.
    """
    if sub.status == "completed":
        log.info(
            "Payment already credited — ignoring | user=%s | ref=%s | source=%s",
            sub.user_key, sub.m_payment_id, source,
        )
        return {"credited": False, "duplicate": True, "tokens": 0, "bonus": 0}

    if from_whatsapp is None:
        from_whatsapp = sub.channel == "whatsapp" or _is_whatsapp_user(db, sub.user_key)

    first_purchase = _is_first_purchase(db, sub.user_key, exclude_payment_id=sub.m_payment_id)

    sub.status = "completed"
    if payment_id:
        sub.payment_token = str(payment_id)
    db.commit()

    tokens_credited = 0
    if tokens_hint and int(tokens_hint) > 0:
        tokens_credited = int(tokens_hint)
        add_credits(db, sub.user_key, tokens_credited)
        log.info("Tokens credited | user=%s | tokens=%d | source=%s", sub.user_key, tokens_credited, source)
    else:
        fallback_pkg = _package_for_amount(_amount_str_to_cents(sub.amount))
        if fallback_pkg is not None:
            tokens_credited = int(fallback_pkg["tokens"])
            add_credits(db, sub.user_key, tokens_credited)
            log.info(
                "Tokens credited (from amount) | user=%s | tokens=%d | source=%s",
                sub.user_key, tokens_credited, source,
            )
        else:
            log.warning(
                "Could not resolve token count for completed payment | user=%s | amount=%s",
                sub.user_key, sub.amount,
            )

    bonus_credited = 0
    bonus = settings.FIRST_PURCHASE_BONUS_TOKENS
    bonus_eligible = tokens_credited >= settings.FIRST_PURCHASE_BONUS_MIN_TOKENS
    if first_purchase and bonus > 0 and bonus_eligible:
        bonus_credited = bonus
        add_credits(db, sub.user_key, bonus)
        log.info("First-purchase bonus credited | user=%s | bonus=%d", sub.user_key, bonus)

    log.info("Token purchase completed | user=%s | source=%s", sub.user_key, source)
    record_server_event(sub.user_key, "purchase_completed", str(sub.amount))

    if from_whatsapp and tokens_credited > 0:
        await _notify_whatsapp_purchase(
            sub.user_key,
            tokens_credited + bonus_credited,
            bonus_credited,
            get_credit_balance(db, sub.user_key),
        )

    return {
        "credited": True,
        "duplicate": False,
        "tokens": tokens_credited,
        "bonus": bonus_credited,
    }


def _reconcile_orphan_checkout(db: Session, meta: dict, payload: dict) -> models.Subscription | None:
    """Last-resort row for a succeeded payment we have no checkout row for.

    The reference is signed by Yoco, so when the metadata still carries
    `user_key` + `tokens` we know exactly who paid for what — refusing to credit
    them just means a charged user with nothing to show for it. Build the row
    the checkout should have written and let the normal path credit it.
    """
    user_key = str(meta.get("user_key") or "").strip()
    try:
        tokens = int(meta.get("tokens") or 0)
    except (TypeError, ValueError):
        tokens = 0
    if not user_key or tokens <= 0:
        return None

    amount_cents = payload.get("amount")
    try:
        amount = f"{int(amount_cents) / 100:.2f}"
    except (TypeError, ValueError):
        pkg = payments.find_package(tokens)
        amount = pkg["price"] if pkg else "0.00"

    sub = models.Subscription(
        user_key=user_key,
        m_payment_id=str(meta.get("m_payment_id")),
        status="pending",
        amount=amount,
        frequency=0,
        channel=str(meta.get("channel") or "") or None,
    )
    db.add(sub)
    db.commit()
    return sub


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
        if event_type != "payment.succeeded":
            log.warning("Yoco webhook unknown m_payment_id=%s", m_payment_id)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
        # Money has changed hands and we have no record of the checkout. Never
        # drop it on the floor — rebuild the row from the signed metadata.
        sub = _reconcile_orphan_checkout(db, meta, payload)
        if sub is None:
            log.error(
                "PAYMENT_RECONCILE unresolvable | ref=%s | metadata=%s — payment succeeded "
                "with no checkout row and no user_key/tokens in metadata",
                m_payment_id, meta,
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
        log.error(
            "PAYMENT_RECONCILE orphan credited | ref=%s | user=%s | tokens=%s | amount=%s — "
            "no checkout row existed; crediting from webhook metadata",
            m_payment_id, sub.user_key, meta.get("tokens"), sub.amount,
        )

    from_whatsapp = meta.get("channel") == "whatsapp" or _is_whatsapp_user(db, sub.user_key)

    if event_type == "payment.succeeded":
        # Yoco delivers webhooks at-least-once and the reconcile sweep may have
        # got there first; credit_successful_payment() no-ops on "completed".
        tokens_hint = meta.get("tokens")

        amount_cents = payload.get("amount")
        if amount_cents is not None:
            expected = _amount_str_to_cents(sub.amount)
            try:
                mismatch = int(amount_cents) != expected
            except (TypeError, ValueError):
                mismatch = True
            if mismatch:
                # A mismatch used to be terminal, which silently ate the payment.
                # The metadata is signed by Yoco, so when it names the buyer and
                # the pack we credit anyway and shout about it in the logs.
                if str(meta.get("user_key") or "").strip() and tokens_hint:
                    log.error(
                        "PAYMENT_RECONCILE amount mismatch credited | ref=%s | user=%s | "
                        "expected=%s | got=%s | tokens=%s",
                        m_payment_id, sub.user_key, expected, amount_cents, tokens_hint,
                    )
                else:
                    log.warning("Yoco webhook amount mismatch | expected=%s | got=%s", expected, amount_cents)
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount mismatch")

        await credit_successful_payment(
            db, sub,
            tokens_hint=int(tokens_hint) if tokens_hint else None,
            payment_id=payload.get("id"),
            source="webhook",
            from_whatsapp=from_whatsapp,
        )
    elif event_type == "payment.failed":
        # Only a checkout still awaiting payment can fail — never walk back a
        # completed one (a stale failure for a superseded attempt is common).
        if sub.status in CREDITABLE_STATUSES:
            sub.status = "failed"
            log.warning("Token purchase payment failed | user=%s", sub.user_key)
            db.commit()
            if from_whatsapp:
                await _notify_whatsapp_payment_failed(sub.user_key)
        else:
            log.info("Yoco webhook failure for non-pending checkout ignored | ref=%s | status=%s",
                     m_payment_id, sub.status)
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
