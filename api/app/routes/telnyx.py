"""
Telnyx inbound SMS webhook.

POST /telnyx/webhook  — receives inbound SMS events from Telnyx.

Configure this URL in the Telnyx Mission Control portal under
Messaging > your number > Inbound Settings > Webhook URL.

Signature: Telnyx signs the raw body with Ed25519 over "{timestamp}|{body}".
Set TELNYX_PUBLIC_KEY from Mission Control → API keys → Public key.

Meta/WhatsApp OTP: if the SMS never appears here, Telnyx did not receive it
(carrier/Meta routing). Try voice verification in Meta, or Telnyx message logs.
"""
from __future__ import annotations

import base64
import json
import re
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app import telnyx_inbound_buffer
from app.logger import get_logger
from app.settings import settings

log = get_logger("carver.telnyx")

router = APIRouter()

_TIMESTAMP_TOLERANCE = 600  # seconds; allow clock skew

_OTP_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def _load_ed25519_public_key(raw: str) -> Ed25519PublicKey:
    """Decode Telnyx public key (PEM or base64 raw 32-byte Ed25519 public key)."""
    stripped = raw.strip()
    if "BEGIN PUBLIC KEY" in stripped or "BEGIN" in stripped:
        key = serialization.load_pem_public_key(stripped.encode("utf-8"))
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("Public key is not Ed25519")
        return key
    decoded = base64.b64decode(stripped)
    if len(decoded) != 32:
        raise ValueError(f"Expected 32-byte Ed25519 public key, got {len(decoded)} bytes")
    return Ed25519PublicKey.from_public_bytes(decoded)


def _verify_telnyx_ed25519(body: bytes, signature_b64: str, timestamp: str) -> bool:
    """
    Verify Telnyx webhook per https://developers.telnyx.com/docs/messaging/messages/receiving-webhooks
    Signed payload: {timestamp}|{raw_json_body}
    """
    if not settings.TELNYX_PUBLIC_KEY:
        log.error("Telnyx webhook rejected: TELNYX_PUBLIC_KEY is not configured")
        return False

    if not signature_b64 or not timestamp:
        log.warning("Telnyx webhook missing signature headers")
        return False

    try:
        ts = int(timestamp)
        if abs(int(time.time()) - ts) > _TIMESTAMP_TOLERANCE:
            log.warning("Telnyx webhook timestamp outside tolerance | ts=%s", timestamp)
            return False
    except (ValueError, TypeError, OSError):
        return False

    signed_message = timestamp.encode("utf-8") + b"|" + body
    try:
        public_key = _load_ed25519_public_key(settings.TELNYX_PUBLIC_KEY)
        sig_bytes = base64.b64decode(signature_b64.strip())
        public_key.verify(sig_bytes, signed_message)
        return True
    except InvalidSignature:
        log.warning("Telnyx Ed25519 signature invalid")
        return False
    except (ValueError, TypeError) as e:
        log.warning("Telnyx public key or signature decode error: %s", e)
        return False


def _process_message_received(record: dict) -> None:
    from_obj = record.get("from") or {}
    from_number = from_obj.get("phone_number") or from_obj.get("alphanumeric_sender_id") or "unknown"
    to_raw = record.get("to") or []
    to_numbers = []
    for t in to_raw:
        if isinstance(t, dict):
            to_numbers.append(t.get("phone_number", "") or "")
    text = record.get("text") or ""
    msg_id = str(record.get("id", ""))

    telnyx_inbound_buffer.record(
        from_number=str(from_number),
        to_numbers=to_numbers,
        text=text,
        msg_id=msg_id,
    )

    log.info(
        "SMS received | from=%s | to=%s | text=%r | id=%s",
        from_number,
        to_numbers,
        text,
        msg_id,
    )
    m = _OTP_RE.search(text)
    if m:
        log.info("SMS contains 6-digit code pattern | id=%s", msg_id)


@router.post("/telnyx/webhook", status_code=status.HTTP_200_OK)
async def telnyx_webhook(request: Request):
    """Receive inbound SMS from Telnyx."""
    body = await request.body()

    sig = request.headers.get("telnyx-signature-ed25519", "")
    ts = request.headers.get("telnyx-timestamp", "")

    if not _verify_telnyx_ed25519(body, sig, ts):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    data = payload.get("data")
    if data is None:
        log.info("Telnyx webhook missing data | keys=%s", list(payload.keys()))
        return JSONResponse(content={"status": "ok"})

    # Single event object (standard shape)
    if isinstance(data, dict):
        events = [data]
    elif isinstance(data, list):
        events = data
    else:
        log.info("Telnyx webhook unexpected data type | type=%s", type(data).__name__)
        return JSONResponse(content={"status": "ok"})

    for ev in events:
        if not isinstance(ev, dict):
            continue
        event_type = ev.get("event_type", "")
        record = ev.get("payload") or {}

        if event_type == "message.received" and isinstance(record, dict):
            _process_message_received(record)
        elif event_type:
            log.info("Telnyx event ignored | type=%s", event_type)

    return JSONResponse(content={"status": "ok"})
