import hashlib
import urllib.parse
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.logger import get_logger
from app.security import require_session
from app.settings import settings

log = get_logger("carver.subscription")

router = APIRouter(prefix="/subscription", tags=["subscription"])

PAYFAST_SANDBOX_URL = "https://sandbox.payfast.co.za/eng/process"
PAYFAST_LIVE_URL = "https://www.payfast.co.za/eng/process"

# PayFast sends ITN from these IP ranges — verify on every webhook.
PAYFAST_VALID_IPS = frozenset({
    "197.97.145.144", "197.97.145.145", "197.97.145.146", "197.97.145.147",
    "197.97.145.148", "197.97.145.149", "197.97.145.150", "197.97.145.151",
    "197.97.145.152", "197.97.145.153", "197.97.145.154", "197.97.145.155",
    "197.97.145.156", "197.97.145.157", "197.97.145.158", "197.97.145.159",
    # Sandbox IPs
    "41.74.179.194",
})

# Field ordering for PayFast signature generation.
SIGNATURE_FIELDS = [
    "merchant_id", "merchant_key", "return_url", "cancel_url", "notify_url",
    "name_first", "name_last", "email_address", "cell_number",
    "m_payment_id", "amount", "item_name", "item_description",
    "custom_int1", "custom_int2", "custom_int3", "custom_int4", "custom_int5",
    "custom_str1", "custom_str2", "custom_str3", "custom_str4", "custom_str5",
    "email_confirmation", "confirmation_address",
    "payment_method", "subscription_type", "billing_date", "recurring_amount",
    "frequency", "cycles",
]


def _generate_signature(data: dict[str, str], passphrase: str | None = None) -> str:
    """Build an MD5 signature from ordered key=value pairs + optional passphrase."""
    parts: list[str] = []
    for key in SIGNATURE_FIELDS:
        if key in data and data[key] != "":
            parts.append(f"{key}={urllib.parse.quote_plus(str(data[key]))}")
    pf_string = "&".join(parts)
    if passphrase:
        pf_string += f"&passphrase={urllib.parse.quote_plus(passphrase)}"
    return hashlib.md5(pf_string.encode()).hexdigest()


def _verify_itn_signature(post_data: dict[str, str], passphrase: str | None = None) -> bool:
    """Verify the signature on an incoming ITN POST from PayFast."""
    submitted_sig = post_data.get("signature", "")
    check_data = {k: v for k, v in post_data.items() if k != "signature" and v.strip()}
    parts: list[str] = []
    for key, val in check_data.items():
        parts.append(f"{key}={urllib.parse.quote_plus(val)}")
    pf_string = "&".join(parts)
    if passphrase:
        pf_string += f"&passphrase={urllib.parse.quote_plus(passphrase)}"
    expected_sig = hashlib.md5(pf_string.encode()).hexdigest()
    return expected_sig == submitted_sig


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _payfast_configured() -> bool:
    return bool(settings.PAYFAST_MERCHANT_ID and settings.PAYFAST_MERCHANT_KEY)


@router.post("/checkout")
def create_checkout(request: Request, session: dict = Depends(require_session), db: Session = Depends(get_db)):
    if not _payfast_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment provider is not configured yet.",
        )

    user_key = session.get("sub", "")
    payment_id = uuid.uuid4().hex

    # Upsert: cancel any existing pending subscription for this user
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
        amount=settings.PAYFAST_MONTHLY_AMOUNT,
        frequency=3,
    )
    db.add(sub)
    db.commit()

    api_base = str(request.base_url).rstrip("/")
    frontend_base = settings.FRONTEND_BASE_URL.rstrip("/")

    data = {
        "merchant_id": settings.PAYFAST_MERCHANT_ID,
        "merchant_key": settings.PAYFAST_MERCHANT_KEY,
        "return_url": f"{frontend_base}/subscription?status=success",
        "cancel_url": f"{frontend_base}/subscription?status=cancelled",
        "notify_url": f"{api_base}/subscription/notify",
        "m_payment_id": payment_id,
        "amount": settings.PAYFAST_MONTHLY_AMOUNT,
        "item_name": "CARVER Pro Monthly",
        "item_description": "CARVER Pro subscription — monthly recurring",
        "email_address": user_key,
        "subscription_type": "1",
        "frequency": "3",
        "cycles": "0",
        "recurring_amount": settings.PAYFAST_MONTHLY_AMOUNT,
    }
    data["signature"] = _generate_signature(data, settings.PAYFAST_PASSPHRASE or None)

    payfast_url = PAYFAST_SANDBOX_URL if settings.PAYFAST_SANDBOX else PAYFAST_LIVE_URL
    log.info("Checkout created | user=%s | payment_id=%s | sandbox=%s", user_key, payment_id, settings.PAYFAST_SANDBOX)
    return {"ok": True, "payfast_url": payfast_url, "form_fields": data}


@router.post("/notify")
async def itn_notify(request: Request, db: Session = Depends(get_db)):
    """PayFast ITN (Instant Transaction Notification) webhook — server-to-server."""
    body = await request.body()
    post_data: dict[str, str] = dict(urllib.parse.parse_qsl(body.decode("utf-8")))
    log.info("ITN received | m_payment_id=%s | status=%s", post_data.get("m_payment_id"), post_data.get("payment_status"))

    # 1. Verify source IP (skip in sandbox for local testing)
    if not settings.PAYFAST_SANDBOX:
        client_ip = _get_client_ip(request)
        if client_ip not in PAYFAST_VALID_IPS:
            log.warning("ITN rejected: invalid source IP %s", client_ip)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid source")

    # 2. Verify signature
    if not _verify_itn_signature(post_data, settings.PAYFAST_PASSPHRASE or None):
        log.warning("ITN rejected: invalid signature | m_payment_id=%s", post_data.get("m_payment_id"))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    # 3. Look up our subscription record
    m_payment_id = post_data.get("m_payment_id", "")
    sub = db.query(models.Subscription).filter(models.Subscription.m_payment_id == m_payment_id).first()
    if not sub:
        log.warning("ITN rejected: unknown m_payment_id=%s", m_payment_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")

    # 4. Verify amount matches
    pf_amount = post_data.get("amount_gross", "")
    if pf_amount and pf_amount != sub.amount:
        log.warning("ITN amount mismatch | expected=%s | got=%s", sub.amount, pf_amount)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount mismatch")

    # 5. Process based on payment status
    payment_status = post_data.get("payment_status", "")
    token = post_data.get("token", "")

    if payment_status == "COMPLETE":
        sub.status = "active"
        sub.payfast_token = token or sub.payfast_token
        sub.next_billing_date = post_data.get("billing_date", "")
        # Also set the user-level flag for quick session lookups
        user = db.query(models.User).filter(models.User.email == sub.user_key).first()
        if user:
            user.is_subscribed = True
        log.info("Subscription activated | user=%s | token=%s", sub.user_key, bool(token))
    elif payment_status == "FAILED":
        sub.status = "failed"
        log.warning("Subscription payment failed | user=%s", sub.user_key)
    elif payment_status == "CANCELLED":
        sub.status = "cancelled"
        user = db.query(models.User).filter(models.User.email == sub.user_key).first()
        if user:
            user.is_subscribed = False
        log.info("Subscription cancelled via ITN | user=%s", sub.user_key)

    db.commit()
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
    sub = (
        db.query(models.Subscription)
        .filter(models.Subscription.user_key == user_key, models.Subscription.status == "active")
        .first()
    )
    if not sub:
        return {"ok": True, "subscribed": False}
    return {
        "ok": True,
        "subscribed": True,
        "next_billing_date": sub.next_billing_date,
        "amount": sub.amount,
    }
