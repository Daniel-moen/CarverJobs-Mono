"""
Telnyx inbound SMS webhook.

POST /telnyx/webhook  — receives inbound SMS events from Telnyx.

Configure this URL in the Telnyx Mission Control portal under
Messaging > your number > Inbound Settings > Webhook URL.
"""
import hashlib
import hmac
import json
import time

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.logger import get_logger
from app.settings import settings

log = get_logger("carver.telnyx")

router = APIRouter()

_TIMESTAMP_TOLERANCE = 300  # reject webhooks older than 5 minutes


def _verify_signature(payload: bytes, signature: str, timestamp: str) -> bool:
    """Verify Telnyx webhook signature (HMAC-SHA256 using your signing secret)."""
    if not settings.TELNYX_WEBHOOK_SECRET:
        log.warning("TELNYX_WEBHOOK_SECRET not set — skipping signature check")
        return True

    try:
        ts = int(timestamp)
        if abs(time.time() - ts) > _TIMESTAMP_TOLERANCE:
            log.warning("Telnyx webhook timestamp too old: %s", timestamp)
            return False
    except (ValueError, TypeError):
        return False

    signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
    expected = hmac.new(
        settings.TELNYX_WEBHOOK_SECRET.encode(),
        signed_payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


@router.post("/telnyx/webhook", status_code=status.HTTP_200_OK)
async def telnyx_webhook(request: Request):
    """Receive inbound SMS from Telnyx."""
    body = await request.body()

    sig = request.headers.get("telnyx-signature-ed25519", "")
    ts = request.headers.get("telnyx-timestamp", "")

    if settings.TELNYX_WEBHOOK_SECRET and not _verify_signature(body, sig, ts):
        log.warning("Telnyx webhook signature verification failed")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("data", {}).get("event_type", "")
    record = payload.get("data", {}).get("payload", {})

    if event_type == "message.received":
        from_number = record.get("from", {}).get("phone_number", "unknown")
        to_numbers = [t.get("phone_number", "") for t in record.get("to", [])]
        text = record.get("text", "")
        msg_id = record.get("id", "")

        log.info(
            "SMS received | from=%s | to=%s | text=%s | id=%s",
            from_number,
            to_numbers,
            text[:100],
            msg_id,
        )

        # TODO: add your business logic here (e.g. forward to WhatsApp handler,
        # store in DB, trigger auto-reply, etc.)

    else:
        log.info("Telnyx event ignored | type=%s", event_type)

    return JSONResponse(content={"status": "ok"})
