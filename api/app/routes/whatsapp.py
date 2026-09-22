"""
WhatsApp bot via Meta Cloud API.

Incoming messages → POST /webhooks/whatsapp
Webhook verification → GET /webhooks/whatsapp
Magic link auth → GET /wa/auth/{token}

Identity: phone number is the user_key used for CrewProfile, Document, JobHistoryEntry.
New users are walked through AI onboarding; existing users get a command router.
Complex actions (doc uploads, full profile edit) are handled via a short-lived magic link
that sets a session cookie and lands the user on the existing web profile page.
"""
from __future__ import annotations
import asyncio

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from contextvars import ContextVar
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import flags, metrics
from app.analytics import record_server_event
from app.database import SessionLocal, get_db
from app.logger import get_logger
from app.models import CrewProfile, Document, Job, JobHistoryEntry, MatchInteraction, MatchSession, MatchSessionResult, WhatsAppMagicToken, WhatsAppMessage, WhatsAppSeenMessage, WhatsAppSession
from app.security import issue_session_token
from app.settings import settings
from app.services.ai_client import AIClientError
from app.services.mixpanel_server import track as mixpanel_track
from app.routes.subscription import _is_first_purchase
from app.services import payments
from app.services.credits import add_credits, award_job_post_credit, crew_match_free, get_credit_balance, is_subscribed, spend_credits
from app.services.feedback_settings import FEEDBACK_REWARD_TOKENS, feedback_is_eligible

log = get_logger("carver.whatsapp")

router = APIRouter(tags=["whatsapp"])

# Shared async client for all Meta Graph API calls. Connection pooling + keep-alive
# lets repeated outbound sends reuse an established TCP/TLS connection instead of
# paying a fresh handshake every message — the biggest latency win for the hot path.
# Split timeouts: a short connect timeout fails fast on a dead network, while a
# longer read/write budget keeps overall behaviour ~equivalent to the old flat 20s
# (no call hangs longer than before; per-call `timeout=` overrides still apply).
_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
_HTTP_LIMITS = httpx.Limits(
    max_connections=20,
    max_keepalive_connections=10,
    keepalive_expiry=30.0,
)
_http = httpx.AsyncClient(timeout=_HTTP_TIMEOUT, limits=_HTTP_LIMITS)

# ── Deduplication ─────────────────────────────────────────────────────────────
# Keep the last 500 processed Meta message IDs in memory as a fast path, backed
# by the durable whatsapp_seen_messages table. The in-memory set alone died with
# the process, so a deploy plus a Meta retry re-processed the message — and a
# re-processed *match* spends the user's token twice.
_SEEN_MSG_IDS: set[str] = set()
_SEEN_MSG_IDS_ORDER: list[str] = []
_SEEN_MSG_MAX = 500
# How long a message id stays on record. Meta's retry window is hours, not days.
_SEEN_MSG_RETENTION_HOURS = 48
_SEEN_MSG_PRUNE_INTERVAL_SECONDS = 3600
_seen_msg_last_prune = 0.0
_STALE_MSG_SECONDS = 300  # don't *process* messages older than 5 minutes
# …but never drop one in silence: the user gets one "I was offline" nudge so
# they know to resend, rather than staring at a message the bot never answered.
_STALE_NOTICE = "I was offline for a bit — say that again?"
_STALE_NOTICE_COOLDOWN_SECONDS = 600
_STALE_NOTICE_MAX_TRACKED = 500
_STALE_NOTICE_SENT_AT: dict[str, float] = {}
# Sent when processing blows up (usually a failed LLM call) — anything is
# better than the user's message vanishing without a reply.
_GLITCH_REPLY = "Hmm, I glitched — say that again?"
_ACTIVE_MATCH_RUNS: set[str] = set()
_ACTIVE_MATCH_RUNS_LOCK = threading.Lock()
_MATCH_SCOPE_ALL = "all"
_MATCH_SCOPE_RECENT = "recent"
_MIXPANEL_CAPTURE_TIMEOUT = 2


def _parse_meta_timestamp(timestamp_str: str | None) -> int | None:
    """Best-effort parse of Meta webhook timestamps to Unix seconds.

    Meta timestamps are expected to be Unix seconds, but in practice we may see
    malformed values or alternate units. Only return a value when it lands in a
    sane range near the current epoch; otherwise skip stale filtering and let
    message ID dedupe protect us.
    """
    if timestamp_str in (None, ""):
        return None

    try:
        raw_ts = int(str(timestamp_str).strip())
    except (ValueError, TypeError):
        return None

    if raw_ts <= 0:
        return None

    now = int(time.time())

    # Normal Unix seconds.
    if 946684800 <= raw_ts <= now + 86400:
        return raw_ts

    # Milliseconds since epoch.
    if 946684800000 <= raw_ts <= (now + 86400) * 1000:
        return raw_ts // 1000

    return None


def _remember_msg_id_in_memory(msg_id: str) -> None:
    _SEEN_MSG_IDS.add(msg_id)
    _SEEN_MSG_IDS_ORDER.append(msg_id)
    if len(_SEEN_MSG_IDS_ORDER) > _SEEN_MSG_MAX:
        oldest = _SEEN_MSG_IDS_ORDER.pop(0)
        _SEEN_MSG_IDS.discard(oldest)


def _prune_seen_messages(db: Session) -> None:
    """Drop message ids older than the retention window, at most hourly."""
    global _seen_msg_last_prune
    now = time.time()
    if now - _seen_msg_last_prune < _SEEN_MSG_PRUNE_INTERVAL_SECONDS:
        return
    _seen_msg_last_prune = now
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_SEEN_MSG_RETENTION_HOURS)
    db.query(WhatsAppSeenMessage).filter(WhatsAppSeenMessage.seen_at < cutoff).delete(
        synchronize_session=False
    )
    db.commit()


def _claim_msg_id(msg_id: str) -> bool:
    """Claim a Meta message id for processing. False when it was already seen.

    Durable half of the dedup: the row survives a deploy, so Meta's retry of a
    message we already answered is dropped instead of re-run. A DB problem here
    must never swallow a real message, so any unexpected failure claims it.
    """
    try:
        db = SessionLocal()
    except Exception as exc:
        log.warning("WhatsApp dedup store unreachable | id=%s | %s", msg_id, exc)
        return True
    try:
        seen = (
            db.query(WhatsAppSeenMessage.msg_id)
            .filter(WhatsAppSeenMessage.msg_id == msg_id)
            .first()
        )
        if seen is not None:
            return False
        db.add(WhatsAppSeenMessage(msg_id=msg_id, seen_at=datetime.now(timezone.utc)))
        db.commit()
        _prune_seen_messages(db)
        return True
    except IntegrityError:
        # Concurrent webhook deliveries of the same message — the other one won.
        db.rollback()
        return False
    except Exception as exc:
        db.rollback()
        log.warning("WhatsApp dedup store unavailable | id=%s | %s", msg_id, exc)
        return True
    finally:
        db.close()


def _inbound_skip_reason(msg_id: str, timestamp_str: str | None) -> str | None:
    """"stale" | "duplicate" when the message must not be processed, else None."""
    # Only stale-drop messages when the timestamp clearly maps to a real Unix
    # epoch. If Meta sends an unexpected format, process it normally.
    msg_ts = _parse_meta_timestamp(timestamp_str)
    if msg_ts is not None:
        age = time.time() - msg_ts
        if age > _STALE_MSG_SECONDS:
            log.warning("WhatsApp stale message skipped | id=%s | age=%.0fs", msg_id, age)
            return "stale"

    # Duplicate check — in-memory fast path first, then the durable table.
    if msg_id in _SEEN_MSG_IDS:
        log.warning("WhatsApp duplicate message skipped | id=%s", msg_id)
        return "duplicate"

    if not _claim_msg_id(msg_id):
        _remember_msg_id_in_memory(msg_id)
        log.warning("WhatsApp duplicate message skipped (durable) | id=%s", msg_id)
        return "duplicate"

    _remember_msg_id_in_memory(msg_id)

    return None


def _should_notify_stale(phone_number: str) -> bool:
    """One "I was offline" reply per user per burst.

    After downtime Meta redelivers the whole backlog at once. Answering every
    stale message in that burst reads as a malfunction, so the first one speaks
    for all of them and the rest stay silent for a cooldown.
    """
    now = time.time()
    last = _STALE_NOTICE_SENT_AT.get(phone_number)
    if last is not None and now - last < _STALE_NOTICE_COOLDOWN_SECONDS:
        return False
    _STALE_NOTICE_SENT_AT[phone_number] = now
    if len(_STALE_NOTICE_SENT_AT) > _STALE_NOTICE_MAX_TRACKED:
        for oldest in sorted(_STALE_NOTICE_SENT_AT, key=_STALE_NOTICE_SENT_AT.get)[
            : _STALE_NOTICE_MAX_TRACKED // 2
        ]:
            _STALE_NOTICE_SENT_AT.pop(oldest, None)
    return True


def _try_start_match_run(phone_number: str) -> bool:
    with _ACTIVE_MATCH_RUNS_LOCK:
        if phone_number in _ACTIVE_MATCH_RUNS:
            return False
        _ACTIVE_MATCH_RUNS.add(phone_number)
        return True


def _finish_match_run(phone_number: str) -> None:
    with _ACTIVE_MATCH_RUNS_LOCK:
        _ACTIVE_MATCH_RUNS.discard(phone_number)

# ── Helpers ──────────────────────────────────────────────────────────────────

_GRAPH_URL = "https://graph.facebook.com/v23.0"

# Inbound webhook sets this so outbound /messages calls use the same Graph phone id.
_wa_graph_phone_id: ContextVar[str | None] = ContextVar("wa_graph_phone_id", default=None)


def _active_wa_phone_number_id() -> str:
    cid = _wa_graph_phone_id.get()
    if cid:
        return cid
    ids = settings.WHATSAPP_PHONE_NUMBER_IDS
    return ids[0] if ids else ""


def _messages_url() -> str:
    return f"{_GRAPH_URL}/{_active_wa_phone_number_id()}/messages"


def _wa_configured() -> bool:
    return bool(settings.WHATSAPP_PHONE_NUMBER_ID and settings.WHATSAPP_ACCESS_TOKEN)


def _mixpanel_whatsapp_distinct_id(phone_number: str) -> str:
    """Stable, non-reversible distinct id for WhatsApp users."""
    raw = f"{settings.SECRET_KEY}:{phone_number}".encode()
    return "whatsapp:" + hashlib.sha256(raw).hexdigest()[:24]


def _capture_whatsapp_mixpanel_event(
    phone_number: str,
    direction: str,
    message_type: str,
    content: str | None,
    *,
    meta_message_id: str | None = None,
    graph_phone_number_id: str | None = None,
    payload: dict | None = None,
) -> None:
    """Best-effort Mixpanel event for WhatsApp traffic; never sends message text."""
    event_name = "whatsapp_message_received" if direction == "inbound" else "whatsapp_message_sent"
    payload = payload or {}
    status_code = payload.get("status_code")
    properties = {
        "channel": "whatsapp",
        "source": "whatsapp",
        "direction": direction,
        "message_type": message_type,
        "message_length": len(content or ""),
        "meta_message_id": meta_message_id or None,
        "graph_phone_number_id": graph_phone_number_id or None,
        "status_code": status_code,
        "success": (int(status_code) < 400) if isinstance(status_code, int) else None,
        "has_error": bool(payload.get("error")),
        "button_count": len(payload.get("buttons") or []) if isinstance(payload.get("buttons"), list) else None,
    }
    mixpanel_track(
        event=event_name,
        distinct_id=_mixpanel_whatsapp_distinct_id(phone_number),
        properties={key: value for key, value in properties.items() if value is not None},
        timeout=_MIXPANEL_CAPTURE_TIMEOUT,
    )


def _record_whatsapp_message(
    phone_number: str,
    direction: str,
    message_type: str,
    content: str | None,
    *,
    meta_message_id: str | None = None,
    graph_phone_number_id: str | None = None,
    payload: dict | None = None,
) -> None:
    """Best-effort audit log for WhatsApp inbound messages and bot replies."""
    db = SessionLocal()
    try:
        db.add(WhatsAppMessage(
            phone_number=phone_number,
            direction=direction,
            message_type=message_type,
            content=content,
            meta_message_id=meta_message_id or None,
            graph_phone_number_id=graph_phone_number_id or None,
            payload_json=json.dumps(payload, ensure_ascii=True, default=str) if payload else None,
        ))
        db.commit()
    except Exception as exc:
        db.rollback()
        log.warning("WhatsApp message audit failed | phone=%s | %s", phone_number[:6] + "****", exc)
    finally:
        db.close()
    _capture_whatsapp_mixpanel_event(
        phone_number,
        direction,
        message_type,
        content,
        meta_message_id=meta_message_id,
        graph_phone_number_id=graph_phone_number_id,
        payload=payload,
    )


def _record_unsupported_inbound_whatsapp_message(
    phone_number: str,
    message_type: str,
    graph_phone_number_id: str = "",
    meta_message_id: str = "",
    *,
    reason: str = "unsupported",
) -> None:
    """Record inbound WhatsApp traffic we do not otherwise process."""
    _record_whatsapp_message(
        phone_number,
        "inbound",
        message_type or "unknown",
        "",
        meta_message_id=meta_message_id,
        graph_phone_number_id=graph_phone_number_id,
        payload={"reason": reason},
    )


def _meta_response_message_id(resp: httpx.Response) -> str | None:
    try:
        messages = resp.json().get("messages") or []
    except ValueError:
        return None
    if not messages:
        return None
    return str((messages[0] or {}).get("id") or "").strip() or None


def _verify_meta_signature(body: bytes, signature_header: str) -> bool:
    """Verify X-Hub-Signature-256 from Meta."""
    if not settings.META_APP_SECRET:
        if settings.APP_ENV == "production":
            log.error("META_APP_SECRET not set in production — rejecting webhook")
            return False
        log.warning("META_APP_SECRET not set — skipping signature verification (dev only)")
        return True
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.META_APP_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header[7:])


async def _send_whatsapp(to: str, text: str) -> None:
    """Send a text message via Meta Cloud API."""
    phone_id = _active_wa_phone_number_id()
    url = f"{_GRAPH_URL}/{phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}
    audit_payload: dict = {"graph_phone_number_id": phone_id}
    meta_message_id = None
    try:
        resp = await _http.post(url, json=payload, headers=headers)
        audit_payload["status_code"] = resp.status_code
        meta_message_id = _meta_response_message_id(resp)
        if resp.status_code >= 400:
            log.error("Meta send failed | to=%s | status=%d | body=%s", to, resp.status_code, resp.text[:300])
        else:
            log.info("WhatsApp message sent | to=%s | chars=%d", to, len(text))
    except httpx.HTTPError as exc:
        audit_payload["error"] = exc.__class__.__name__
        log.exception("WhatsApp send error | to=%s | %s", to, exc)
    finally:
        _record_whatsapp_message(
            to,
            "outbound",
            "text",
            text,
            meta_message_id=meta_message_id,
            graph_phone_number_id=phone_id,
            payload=audit_payload,
        )


async def _send_typing_indicator(message_id: str) -> None:
    """Mark an inbound message as read and show the typing indicator in the chat.

    The indicator stays visible for up to 25 seconds or until our next message
    lands, whichever comes first. Best-effort: a failure here must never block
    the actual reply, and re-sending for an already-read message is harmless.
    """
    if not message_id:
        return
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"},
    }
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}
    try:
        resp = await _http.post(_messages_url(), json=payload, headers=headers)
        if resp.status_code >= 400:
            log.warning("Meta typing indicator failed | status=%d | body=%s", resp.status_code, resp.text[:200])
    except httpx.HTTPError as exc:
        log.warning("WhatsApp typing indicator error | %s", exc)


async def _send_whatsapp_buttons(to: str, body: str, buttons: list[tuple[str, str]]) -> None:
    """Send an interactive quick-reply button message (up to 3 buttons)."""
    phone_id = _active_wa_phone_number_id()
    url = f"{_GRAPH_URL}/{phone_id}/messages"
    top_buttons = buttons[:3]
    btn_list = [
        {"type": "reply", "reply": {"id": bid, "title": title[:20]}}
        for bid, title in top_buttons
    ]
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {"buttons": btn_list},
        },
    }
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}
    audit_payload: dict = {
        "graph_phone_number_id": phone_id,
        "buttons": [{"id": bid, "title": title[:20]} for bid, title in top_buttons],
    }
    meta_message_id = None
    try:
        resp = await _http.post(url, json=payload, headers=headers)
        audit_payload["status_code"] = resp.status_code
        meta_message_id = _meta_response_message_id(resp)
        if resp.status_code >= 400:
            log.error("Meta buttons send failed | to=%s | status=%d | body=%s", to, resp.status_code, resp.text[:300])
    except httpx.HTTPError as exc:
        audit_payload["error"] = exc.__class__.__name__
        log.exception("WhatsApp buttons send error | to=%s | %s", to, exc)
    finally:
        _record_whatsapp_message(
            to,
            "outbound",
            "interactive_button",
            body,
            meta_message_id=meta_message_id,
            graph_phone_number_id=phone_id,
            payload=audit_payload,
        )


async def _send_whatsapp_list(
    to: str,
    *,
    header: str,
    body: str,
    footer: str,
    button: str,
    rows: list[dict],
    section_title: str,
) -> None:
    """Send an interactive list message (up to 10 rows of {id,title,description})."""
    phone_id = _active_wa_phone_number_id()
    url = f"{_GRAPH_URL}/{phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": header[:60]},
            "body": {"text": body},
            "footer": {"text": footer[:60]},
            "action": {
                "button": button[:20],
                "sections": [{"title": section_title[:24], "rows": rows[:10]}],
            },
        },
    }
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}
    audit_payload: dict = {
        "graph_phone_number_id": phone_id,
        "rows": [{"id": r.get("id"), "title": r.get("title")} for r in rows[:10]],
    }
    meta_message_id = None
    try:
        resp = await _http.post(url, json=payload, headers=headers)
        audit_payload["status_code"] = resp.status_code
        meta_message_id = _meta_response_message_id(resp)
        if resp.status_code >= 400:
            log.error("Meta list send failed | to=%s | status=%d | body=%s", to, resp.status_code, resp.text[:300])
    except httpx.HTTPError as exc:
        audit_payload["error"] = exc.__class__.__name__
        log.exception("WhatsApp list send error | to=%s | %s", to, exc)
    finally:
        _record_whatsapp_message(
            to,
            "outbound",
            "interactive_list",
            body,
            meta_message_id=meta_message_id,
            graph_phone_number_id=phone_id,
            payload=audit_payload,
        )


async def _send_whatsapp_cta_url(
    to: str,
    *,
    body: str,
    button_text: str,
    url_link: str,
    header: str | None = None,
    footer: str | None = None,
) -> None:
    """Send an interactive CTA-URL message — a tappable button that opens a link.

    Replaces pasting raw magic-link/payment URLs into the message body: the
    button hides the long token URL and reads as a native action.
    """
    phone_id = _active_wa_phone_number_id()
    url = f"{_GRAPH_URL}/{phone_id}/messages"
    interactive: dict = {
        "type": "cta_url",
        "body": {"text": body},
        "action": {
            "name": "cta_url",
            "parameters": {"display_text": button_text[:20], "url": url_link},
        },
    }
    if header:
        interactive["header"] = {"type": "text", "text": header[:60]}
    if footer:
        interactive["footer"] = {"text": footer[:60]}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": interactive,
    }
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}
    audit_payload: dict = {
        "graph_phone_number_id": phone_id,
        "cta": {"display_text": button_text[:20], "url": url_link},
    }
    meta_message_id = None
    try:
        resp = await _http.post(url, json=payload, headers=headers)
        audit_payload["status_code"] = resp.status_code
        meta_message_id = _meta_response_message_id(resp)
        if resp.status_code >= 400:
            log.error("Meta CTA send failed | to=%s | status=%d | body=%s", to, resp.status_code, resp.text[:300])
    except httpx.HTTPError as exc:
        audit_payload["error"] = exc.__class__.__name__
        log.exception("WhatsApp CTA send error | to=%s | %s", to, exc)
    finally:
        _record_whatsapp_message(
            to,
            "outbound",
            "interactive_cta_url",
            body,
            meta_message_id=meta_message_id,
            graph_phone_number_id=phone_id,
            payload=audit_payload,
        )


# Instant acks sent the moment a job submission lands, before the slow
# download/AI-extraction work, so the user isn't left staring at silence.
_JOB_REVIEW_WAIT_ACKS = {
    "image": "📸 Got it — reading your screenshot now… this can take a moment.",
    "text": "📝 Reading that job post… this can take a moment.",
}


async def _send_job_review_wait(to: str, kind: str = "text") -> None:
    """Instant ack while AI reviews a job submission, tailored to the input type."""
    await _send_whatsapp(
        to,
        _JOB_REVIEW_WAIT_ACKS.get(kind, _JOB_REVIEW_WAIT_ACKS["text"]),
    )


async def _send_match_scope_menu(to: str) -> None:
    """Ask the WhatsApp user which job set to use for matching."""
    await _send_whatsapp_buttons(
        to,
        "🎯 *Find Matches* uses *1 token* per run.\n\nWhich jobs should I scan?",
        [
            ("btn_match_recent", "Recent Posts"),
            ("btn_match_all", "All DB Jobs"),
            ("btn_menu", "Menu"),
        ],
    )

def _credits_summary_for_menu(balance: int, subscribed: bool = False) -> str:
    w = "token" if balance == 1 else "tokens"
    if crew_match_free():
        # Nothing to sell while runs are free — saying otherwise is just noise.
        return (
            f"💳 *Your balance: {balance} {w}.*\n"
            "*Find Matches* runs are free right now — run as many as you like."
        )
    return (
        f"💳 *Your balance: {balance} {w}.*\n"
        "Each *Find Matches* run uses 1 token. "
        "Type *buy tokens* to top up, or submit a valid job to earn a free token."
    )


def _credits_standalone_message(balance: int, subscribed: bool = False) -> str:
    """Full explainer for *balance* / *tokens* text commands."""
    return _credits_summary_for_menu(balance, subscribed)


async def _send_help_menu(to: str, db: Session) -> None:
    """Send interactive list menu with all available commands."""
    balance = get_credit_balance(db, to)
    sub = is_subscribed(db, to)
    # The list is already at WhatsApp's 10-row ceiling, so the referral loop
    # earns its discoverability in the body instead of a row of its own.
    body_text = (
        f"What would you like to do?\n\n{_credits_summary_for_menu(balance, sub)}\n\n"
        f"🤝 Type *refer* to invite a friend — you both get {_REFERRAL_BONUS_TOKENS} match runs."
    )
    url = _messages_url()
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": "CARVER 🛥️"},
            "body": {"text": body_text},
            "footer": {"text": "Superyacht crew jobs & job board"},
            "action": {
                "button": "Show Menu",
                "sections": [
                    {
                        "title": "My Profile",
                        "rows": [
                            {"id": "cmd_profile", "title": "View Profile", "description": "See your crew profile summary"},
                            {"id": "cmd_edit", "title": "Edit Profile", "description": "Update your crew profile"},
                            {"id": "cmd_docs", "title": "My Documents", "description": "CV, passport, STCW & certs"},
                            {"id": "cmd_upload", "title": "Upload Docs", "description": "Upload crew docs for vessels"},
                        ],
                    },
                    {
                        "title": "Jobs",
                        "rows": [
                            {
                                "id": "cmd_match",
                                "title": "Find Matches",
                                "description": "Choose recent posts or all database jobs",
                            },
                            {"id": "cmd_jobs", "title": "Browse Job Board", "description": "View open yacht positions"},
                            {"id": "cmd_saved", "title": "My Jobs", "description": "Jobs you saved from match runs"},
                            {
                                "id": "cmd_submit_job",
                                "title": "Submit a Job",
                                "description": "From groups or posts—screenshot or paste",
                            },
                        ],
                    },
                    {
                        "title": "Account",
                        "rows": [
                            {
                                "id": "cmd_credits",
                                "title": "My balance",
                                "description": "Tokens & how matching works",
                            },
                            {
                                "id": "cmd_subscribe",
                                "title": "Buy Tokens",
                                "description": "Top up your token balance",
                            },
                        ],
                    },
                ],
            },
        },
    }
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}
    audit_payload: dict = {
        "graph_phone_number_id": _active_wa_phone_number_id(),
        "sections": [
            {
                "title": section.get("title"),
                "rows": [
                    {"id": row.get("id"), "title": row.get("title")}
                    for row in section.get("rows", [])
                ],
            }
            for section in payload["interactive"]["action"]["sections"]
        ],
    }
    meta_message_id = None
    try:
        resp = await _http.post(url, json=payload, headers=headers)
        audit_payload["status_code"] = resp.status_code
        meta_message_id = _meta_response_message_id(resp)
        if resp.status_code >= 400:
            log.error("Meta list send failed | to=%s | status=%d | body=%s", to, resp.status_code, resp.text[:300])
    except httpx.HTTPError as exc:
        audit_payload["error"] = exc.__class__.__name__
        log.exception("WhatsApp list send error | to=%s | %s", to, exc)
    finally:
        _record_whatsapp_message(
            to,
            "outbound",
            "interactive_list",
            body_text,
            meta_message_id=meta_message_id,
            graph_phone_number_id=_active_wa_phone_number_id(),
            payload=audit_payload,
        )


# ── WhatsApp media download ───────────────────────────────────────────────────

_WA_IMAGE_MAX_BYTES = 8 * 1024 * 1024  # 8 MB — same limit as admin screenshot import
_WA_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}


async def _download_whatsapp_media(media_id: str) -> tuple[bytes, str]:
    """Download a media file from Meta Cloud API by media ID.

    Returns (file_bytes, mime_type).  Raises ValueError on failure.
    """
    meta_url = f"{_GRAPH_URL}/{media_id}"
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}

    resp = await _http.get(meta_url, headers=headers)
    if resp.status_code >= 400:
        raise ValueError(f"Meta media lookup failed: HTTP {resp.status_code}")

    info = resp.json()
    download_url = info.get("url")
    mime_type = info.get("mime_type", "image/jpeg")
    if not download_url:
        raise ValueError("No download URL in Meta media response")

    dl_resp = await _http.get(download_url, headers=headers, timeout=30.0)
    if dl_resp.status_code >= 400:
        raise ValueError(f"Media download failed: HTTP {dl_resp.status_code}")

    return dl_resp.content, mime_type


# ── Job submission via WhatsApp ───────────────────────────────────────────────

async def _send_job_posted_confirmation(phone_number: str, job: Job, award: dict) -> None:
    """Confirm a saved job submission, honest about whether a token was earned.

    `award` is the dict returned by `award_job_post_credit` — when the monthly
    free-token cap is hit, `granted` is False and promising "you earned a
    token" would be a lie that erodes trust at the exact moment we could be
    selling a pack instead.
    """
    title = job.title or "Yacht Crew Position"
    role = job.role or "Crew"
    location = job.location or "Unknown"
    # Growth loop: the submitter is standing in the group the job came from,
    # so the cheapest distribution we will ever get is asking them to paste the
    # public board back into it.
    share_line = (
        "\n\nIf it came from a group, paste this back there so the crew can find it: "
        f"{settings.FRONTEND_BASE_URL.rstrip('/')}/jobs/board (or reply JOBS in WhatsApp)"
    )
    balance = award["balance"]
    balance_w = "token" if balance == 1 else "tokens"
    header = (
        f"✅ *Job posted to the board!*\n\n"
        f"⚓ *{title}*\n"
        f"🧑‍✈️ Role: {role}\n"
        f"📍 Location: {location}\n\n"
    )
    if award["granted"]:
        await _send_whatsapp(
            phone_number,
            header
            + f"You earned *1 token* for sharing this job.\n"
            f"Current balance: *{balance}* {balance_w}.\n\n"
            f"_The listing is now live for crew to see._"
            + share_line,
        )
        return

    cap = settings.FREE_JOB_POST_TOKENS_PER_MONTH
    await _send_whatsapp(
        phone_number,
        header
        + f"Thanks for sharing — the listing is now live for crew to see! 🙌\n\n"
        f"You've already earned your *{cap} free tokens* from job posts this "
        f"month, so no token this time — the counter resets every 30 days.\n"
        f"Current balance: *{balance}* {balance_w}."
        + share_line,
    )
    await _send_whatsapp_buttons(
        phone_number,
        "Need more tokens before the reset?",
        [("cmd_subscribe", "Buy Tokens"), ("btn_menu", "Menu")],
    )


async def _process_job_text_submission(phone_number: str, text: str, db: Session) -> None:
    """AI-review a text message as a potential job posting and save to the board."""
    import asyncio
    from app.services.ai_job_reviewer import review_post
    from app.services.job_sync import _build_job_fields, _content_hash

    ai_fields = await asyncio.to_thread(
        review_post,
        post_text=text,
        post_url="whatsapp",
        api_key=settings.OPENAI_API_KEY,
        model=settings.OPENAI_MODEL,
    )
    if ai_fields is None:
        await _send_whatsapp(
            phone_number,
            "🤔 That doesn't look like a yacht crew job posting — could you try again with the full listing text or a screenshot?",
        )
        return

    fields = _build_job_fields(ai_fields, {"url": "", "text": text}, "manual")
    fields["source"] = "whatsapp_submit"
    h = _content_hash(text)
    fields["content_hash"] = h

    if h:
        existing = db.query(Job.id).filter(Job.content_hash == h).first()
        if existing:
            await _send_whatsapp(phone_number, "⚠️ This job is already on the board — no duplicate created.")
            return

    if fields.get("application_url"):
        existing = db.query(Job.id).filter(Job.application_url == fields["application_url"]).first()
        if existing:
            await _send_whatsapp(phone_number, "⚠️ This job is already on the board — no duplicate created.")
            return

    job = Job(**fields)
    db.add(job)
    db.commit()
    db.refresh(job)
    award = award_job_post_credit(db, phone_number)

    metrics.increment("whatsapp_job_submissions")
    await _send_job_posted_confirmation(phone_number, job, award)


async def _process_job_image_submission(phone_number: str, media_id: str, db: Session) -> None:
    """Download a WhatsApp image, AI-scan it for a job posting, and save to the board."""
    import asyncio
    import json as _json
    from app.services.ai_client import review_job_image
    from app.services.ai_job_reviewer import _SYSTEM_PROMPT
    from app.services.job_sync import _build_job_fields

    try:
        image_bytes, mime_type = await _download_whatsapp_media(media_id)
    except (ValueError, httpx.HTTPError) as exc:
        log.error("WhatsApp job image download failed | phone=%s | %s", phone_number[:6] + "****", exc)
        await _send_whatsapp(phone_number, "⚠️ Couldn't download the image — please try sending it again.")
        return

    if mime_type not in _WA_IMAGE_MIME_TYPES:
        await _send_whatsapp(phone_number, "⚠️ Please send a PNG, JPEG, or WebP screenshot of the job posting.")
        return

    if len(image_bytes) > _WA_IMAGE_MAX_BYTES:
        await _send_whatsapp(phone_number, "⚠️ Image is too large (max 8 MB). Try cropping or compressing it.")
        return

    try:
        raw_json = await asyncio.to_thread(
            review_job_image,
            api_key=settings.OPENAI_API_KEY,
            image_bytes=image_bytes,
            mime_type=mime_type,
            model=settings.OPENAI_MODEL,
            system_prompt=_SYSTEM_PROMPT,
        )
        parsed = _json.loads(raw_json)
    except (AIClientError, _json.JSONDecodeError, TypeError) as exc:
        log.error("WhatsApp job image AI review failed | phone=%s | %s", phone_number[:6] + "****", exc)
        await _send_whatsapp(phone_number, "⚠️ Couldn't read the screenshot — try a clearer image or paste the text instead.")
        return

    if not parsed.get("is_job"):
        await _send_whatsapp(
            phone_number,
            "🤔 The AI couldn't identify a yacht crew job in that image — try a clearer screenshot or paste the text.",
        )
        return

    parsed.pop("is_job", None)
    fields = _build_job_fields(parsed, {"url": ""}, "manual")
    fields["source"] = "whatsapp_submit"

    if fields.get("application_url"):
        existing = db.query(Job.id).filter(Job.application_url == fields["application_url"]).first()
        if existing:
            await _send_whatsapp(phone_number, "⚠️ This job is already on the board — no duplicate created.")
            return

    job = Job(**fields)
    db.add(job)
    db.commit()
    db.refresh(job)
    award = award_job_post_credit(db, phone_number)

    metrics.increment("whatsapp_job_submissions")
    await _send_job_posted_confirmation(phone_number, job, award)


# Maps interactive button/list reply IDs to plain-text command strings
_INTERACTIVE_CMD_MAP: dict[str, str] = {
    "cmd_profile": "profile",
    "cmd_docs": "docs",
    "cmd_upload": "upload",
    "cmd_edit": "edit",
    "cmd_match": "match",
    "cmd_match_recent": "match recent",
    "cmd_match_all": "match all",
    "cmd_jobs": "jobs",
    "cmd_saved": "saved",
    "cmd_submit_job": "submit job",
    "cmd_credits": "credits",
    "cmd_subscribe": "subscribe",
    "cmd_cancel_sub": "cancel subscription",
    "cmd_help": "help",
    "btn_find_matches": "match",
    "btn_match_recent": "match recent",
    "btn_match_all": "match all",
    "btn_edit_profile": "edit",
    "btn_upload_docs": "upload",
    "btn_view_profile": "profile",
    "btn_submit_job": "submit job",
    "btn_help": "help",
    "btn_menu": "help",
}

# Per-result buttons under each match detail ("save 3", "dismiss 3", "draft 3").
# Draft reuses the existing text command; save/dismiss route to the new handlers.
_INTERACTIVE_CMD_MAP.update({f"btn_save_{i}": f"save {i}" for i in range(1, 10)})
_INTERACTIVE_CMD_MAP.update({f"btn_dismiss_{i}": f"dismiss {i}" for i in range(1, 10)})
_INTERACTIVE_CMD_MAP.update({f"btn_draft_{i}": f"draft {i}" for i in range(1, 10)})

# Post-run 👍/👎 quality pulse + next-day "did you apply?" follow-up.
_INTERACTIVE_CMD_MAP.update({
    "btn_match_good": "match feedback good",
    "btn_match_bad": "match feedback bad",
    "btn_applied_yes": "applied yes",
    "btn_applied_notyet": "applied not yet",
    "btn_applied_none": "applied none",
})

# Inverted-onboarding preview buttons ("Rank them for me" / "Just show the list").
_INTERACTIVE_CMD_MAP.update({
    "btn_onb_rank": "rank them for me",
    "btn_onb_list": "just show the list",
})


_ALLOWED_REDIRECTS = frozenset({
    "/profile", "/jobs", "/status", "/", "/subscription", "/?feedback=1",
})
_ALLOWED_REDIRECT_PREFIXES = ("/matches/",)


def _link_expiry_note() -> str:
    """Human-readable validity window for magic links, derived from settings."""
    hours = settings.WA_MAGIC_TOKEN_TTL_SECONDS // 3600
    if hours >= 1:
        return f"_Link valid for {hours} hour{'s' if hours != 1 else ''}._"
    minutes = max(1, settings.WA_MAGIC_TOKEN_TTL_SECONDS // 60)
    return f"_Link valid for {minutes} min._"


def _is_safe_redirect(path: str | None) -> bool:
    """Check if a redirect path is allowed (exact match or prefix)."""
    if not path:
        return False
    if path in _ALLOWED_REDIRECTS:
        return True
    return any(path.startswith(p) for p in _ALLOWED_REDIRECT_PREFIXES)


def _make_magic_link(phone_number: str, db: Session, *, redirect_to: str | None = None) -> str:
    """Create a WhatsAppMagicToken and return the full magic link URL.

    ``redirect_to`` must be a known internal path (validated against an allowlist
    to prevent open-redirect attacks).  Defaults to ``/profile`` when omitted.
    Tokens are reusable within their TTL window.

    The redirect is stored in the DB *and* encoded as a ``?r=`` query param
    so the frontend has a fallback even if the DB value is lost.
    """
    safe_redirect = redirect_to if _is_safe_redirect(redirect_to) else None
    token = secrets.token_urlsafe(16)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.WA_MAGIC_TOKEN_TTL_SECONDS)

    from sqlalchemy.exc import OperationalError
    for attempt in range(3):
        try:
            db.add(WhatsAppMagicToken(
                token=token, phone_number=phone_number,
                expires_at=expires_at, redirect_to=safe_redirect,
            ))
            db.commit()
            break
        except OperationalError:
            db.rollback()
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))

    url = f"{settings.FRONTEND_BASE_URL}/wa/{token}"
    if safe_redirect and safe_redirect != "/profile":
        url += f"?r={safe_redirect}"
    return url


def _get_or_create_session(phone_number: str, db: Session) -> WhatsAppSession:
    session = db.query(WhatsAppSession).filter(WhatsAppSession.phone_number == phone_number).first()
    if not session:
        session = WhatsAppSession(phone_number=phone_number)
        db.add(session)
        db.commit()
        db.refresh(session)
        metrics.increment("onboard_started")
        record_server_event(phone_number, "wa_signup")
        # Durable twin of the in-memory counter — funnel maths must survive deploys.
        record_server_event(phone_number, "onboard_started", "whatsapp")
        # Transient (never persisted) marker so the caller can tag acquisition
        # source off the very first inbound message.
        session.is_new_contact = True
    return session


# ── Referral loop ─────────────────────────────────────────────────────────────
# The product had no growth loop at all: every user arrived through a paid or
# hand-placed link and told nobody. The referral code rides the acquisition-tag
# mechanism that already exists — "Hi Carver · REF-AB12CD" is just a first
# message with a tag — so nothing new has to be parsed or stored to attribute it.
_REFERRAL_PREFIX = "REF-"
_REFERRAL_CODE_LEN = 6
# Paid to BOTH sides when the invited user finishes onboarding. Two runs is a
# real gift (a run is the unit we sell) without being worth farming.
_REFERRAL_BONUS_TOKENS = 2
# Falls back to the number the website's wa.me CTAs already hardcode.
_REFERRAL_WA_NUMBER_FALLBACK = "27688516141"


def _referral_code(phone_number: str) -> str:
    """Stable per-user code, e.g. "REF-AB12CD".

    Derived from the phone number rather than stored, so it needs no column,
    no uniqueness check and no backfill — the same user always gets the same
    code, and the code never leaks the number it came from.
    """
    digest = hashlib.sha256(f"carver-referral:{phone_number}".encode()).digest()
    return _REFERRAL_PREFIX + base64.b32encode(digest).decode("ascii")[:_REFERRAL_CODE_LEN]


def _resolve_referral_code(db: Session, code: str | None) -> str | None:
    """Phone number behind a REF- code, or None (unknown code / not a code).

    The code is a one-way hash, so resolution is a scan of existing sessions.
    That is fine at this scale and self-limiting: only a first contact whose
    tag starts with REF- ever reaches it.
    """
    code = (code or "").strip().upper()
    if not code.startswith(_REFERRAL_PREFIX) or len(code) != len(_REFERRAL_PREFIX) + _REFERRAL_CODE_LEN:
        return None
    for (phone,) in db.query(WhatsAppSession.phone_number).all():
        if _referral_code(phone) == code:
            return phone
    return None


def _referral_link(phone_number: str) -> str:
    """wa.me deep link whose prefill carries this user's code as the tag."""
    number = settings.WHATSAPP_PUBLIC_NUMBER or _REFERRAL_WA_NUMBER_FALLBACK
    text = f"Hi Carver · {_referral_code(phone_number)}"
    return f"https://wa.me/{number}?text={quote(text, safe='')}"


def _referral_invite_line(phone_number: str) -> str:
    """One-line share prompt appended to every completed match run."""
    return (
        f"Know someone job hunting? Send them this — you both get "
        f"{_REFERRAL_BONUS_TOKENS} extra match runs: {_referral_link(phone_number)}"
    )


def _credit_referral(wa_session: WhatsAppSession, db: Session) -> str | None:
    """Pay both sides of a referral, once. Returns the referrer's number or None.

    Called when the invited user completes onboarding — the first point at
    which they are a real user rather than a click. `referral_credited` is set
    (and committed) before any token moves, so a retry can never pay twice.
    """
    referrer = getattr(wa_session, "referred_by", None)
    if not referrer or getattr(wa_session, "referral_credited", False):
        return None
    if referrer == wa_session.phone_number:
        return None  # self-referral — belt and braces, also blocked at signup

    wa_session.referral_credited = True
    db.commit()

    add_credits(db, wa_session.phone_number, _REFERRAL_BONUS_TOKENS)
    add_credits(db, referrer, _REFERRAL_BONUS_TOKENS)
    record_server_event(wa_session.phone_number, "referral_completed", "invitee")
    record_server_event(referrer, "referral_completed", "referrer")
    log.info(
        "WhatsApp referral credited | invitee=%s | referrer=%s | tokens=%d",
        wa_session.phone_number[:6] + "****", referrer[:6] + "****", _REFERRAL_BONUS_TOKENS,
    )
    return referrer


async def _notify_referrer(referrer: str, db: Session) -> None:
    """Tell the referrer their invite landed. Never raises into onboarding."""
    try:
        ref_session = (
            db.query(WhatsAppSession)
            .filter(WhatsAppSession.phone_number == referrer)
            .first()
        )
        if ref_session is not None and getattr(ref_session, "opted_out", False):
            return  # Meta compliance: no bot-initiated message to an opt-out
        bal = get_credit_balance(db, referrer)
        w = "token" if bal == 1 else "tokens"
        await _send_whatsapp(
            referrer,
            f"🎁 Someone you invited just joined CARVER — *+{_REFERRAL_BONUS_TOKENS} match runs* "
            f"are on your account. You're at *{bal}* {w}.\n\n"
            "Type *refer* for your link anytime.",
        )
    except Exception as exc:
        log.warning("Referral notify failed | phone=%s | %s", referrer[:6] + "****", exc)


# ── Acquisition source ───────────────────────────────────────────────────────
# The website's wa.me CTAs append a source tag to the prefill text, e.g.
# "match · m-hero" / "match · sticky" / "match · pricing" / "match · article".
# It is parsed off the first inbound message, stored for funnel attribution and
# stripped before anything else sees it — the bot must never answer the tag.
_SOURCE_TAG_RE = re.compile(r"\s*·\s*([A-Za-z0-9][A-Za-z0-9 _.\-]{0,38})\s*$")
# Recorded when a first contact carries no tag (typed the number in, saved
# contact, QR code) so the flag is always set and never re-parsed.
_SOURCE_DIRECT = "direct"


def _split_source_tag(text: str) -> tuple[str, str | None]:
    """("match", "m-hero") from "match · m-hero"; (text, None) when untagged."""
    match = _SOURCE_TAG_RE.search(text or "")
    if not match:
        return text, None
    return text[: match.start()].strip(), match.group(1).strip()


def _is_first_contact(wa_session: WhatsAppSession) -> bool:
    """True only for the very first inbound message of a brand-new user."""
    if getattr(wa_session, "acquisition_source", None):
        return False
    if getattr(wa_session, "is_new_contact", False):
        return True
    # Pre-existing sessions from before the column landed: the history is still
    # empty only on the very first turn.
    return (getattr(wa_session, "history", None) or "[]") == "[]"


def _record_first_contact(
    phone_number: str, wa_session: WhatsAppSession, user_text: str, db: Session
) -> str:
    """Store where this user came from; return their message minus the tag."""
    text, tag = _split_source_tag(user_text)
    source = (tag or _SOURCE_DIRECT)[:40]
    wa_session.acquisition_source = source
    # A REF- tag is also a person: link the two sessions so both get paid when
    # this user finishes onboarding. Every other tag (SCHOOL-…, m-hero, …) is
    # attribution only and stops at acquisition_source.
    referrer = _resolve_referral_code(db, source)
    if referrer and referrer != phone_number:
        wa_session.referred_by = referrer
        record_server_event(phone_number, "referral_signup", source)
    db.commit()
    record_server_event(phone_number, "wa_first_contact", source)
    log.info(
        "WhatsApp first contact | phone=%s | source=%s",
        phone_number[:6] + "****", source,
    )
    # A message that was *only* a tag still has to say something to the bot.
    return text or user_text


# ── Opt-out (Meta compliance) ────────────────────────────────────────────────
# Meta requires an honoured opt-out before any business-initiated messaging.
# Matched against the whole trimmed message, case-insensitively: "stop" on its
# own unsubscribes, "stop sending deck jobs" is an ordinary message.
_OPT_OUT_KEYWORDS: frozenset[str] = frozenset({"stop", "unsubscribe", "opt out", "optout"})
_OPT_IN_KEYWORDS: frozenset[str] = frozenset({"start"})

_OPT_OUT_REPLY = (
    "You're unsubscribed — I won't message you first anymore. "
    "Reply START anytime to switch alerts back on."
)
_OPT_IN_REPLY = (
    "✅ You're back on — I'll ping you when jobs that fit you land.\n\n"
    "Reply *STOP* anytime to switch them off again."
)


async def _handle_opt_out_keywords(
    phone_number: str, wa_session: WhatsAppSession, user_text: str, db: Session
) -> bool:
    """STOP / START handling. True when the message was one and is fully handled.

    Runs *before* command routing: "unsubscribe" used to land on the billing
    reply ("no recurring plan to cancel") and "stop" opened the help menu, so
    neither opt-out word actually opted anyone out.
    """
    cmd = (user_text or "").strip().lower()
    phone = phone_number

    if cmd in _OPT_OUT_KEYWORDS:
        wa_session.opted_out = True
        wa_session.opted_out_at = datetime.now(timezone.utc)
        db.commit()
        record_server_event(phone, "wa_opted_out", cmd)
        log.info("WhatsApp opt-out | phone=%s | keyword=%s", phone[:6] + "****", cmd)
        await _send_whatsapp(phone, _OPT_OUT_REPLY)
        return True

    # "start" is only special for someone who opted out — for everyone else it
    # falls through to the normal router (which opens the menu).
    if cmd in _OPT_IN_KEYWORDS and getattr(wa_session, "opted_out", False):
        wa_session.opted_out = False
        wa_session.opted_out_at = None
        db.commit()
        record_server_event(phone, "wa_opted_in", cmd)
        log.info("WhatsApp opt-in | phone=%s", phone[:6] + "****")
        await _send_whatsapp(phone, _OPT_IN_REPLY)
        return True

    return False


def _save_session(session: WhatsAppSession, db: Session, history: list, partial_profile: dict, mode: str | None = None) -> None:
    session.history = json.dumps(history)
    session.partial_profile = json.dumps(partial_profile)
    if mode:
        session.mode = mode
    db.commit()


def _feedback_already_submitted(db: Session, user_key: str) -> bool:
    from app.models import FeedbackSubmission
    from app.services.feedback_settings import FEEDBACK_CAMPAIGN
    return (
        db.query(FeedbackSubmission.id)
        .filter(
            FeedbackSubmission.user_key == user_key,
            FeedbackSubmission.campaign == FEEDBACK_CAMPAIGN,
        )
        .first()
    ) is not None


# Minimum days between in-chat feedback invitations — the invite rides along
# after a normal reply and must never turn into a nag.
_FEEDBACK_PROMPT_COOLDOWN_DAYS = 7


def _feedback_prompt_due(wa_session: WhatsAppSession) -> bool:
    last = wa_session.feedback_prompted_at
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last >= timedelta(days=_FEEDBACK_PROMPT_COOLDOWN_DAYS)


async def _send_feedback_request(phone: str, db: Session) -> None:
    link = _make_magic_link(phone, db, redirect_to="/?feedback=1")
    # Only promise a reward that will actually be granted (FEEDBACK_REWARD_TOKENS
    # may be 0 — the form still works, it just isn't incentivised).
    if FEEDBACK_REWARD_TOKENS > 0:
        w = "token" if FEEDBACK_REWARD_TOKENS == 1 else "tokens"
        reward_line = f"We'll add *{FEEDBACK_REWARD_TOKENS} {w}* to your account when you submit it."
        footer = "Under 2 min · Reward once per user"
    else:
        reward_line = "It helps us make CARVER better for you."
        footer = "Takes less than 2 minutes"
    await _send_whatsapp_cta_url(
        phone,
        header="Quick feedback 💬",
        body=(
            "Please complete this short feedback form about your CARVER experience. "
            f"{reward_line}"
        ),
        button_text="Open form",
        url_link=link,
        footer=footer,
    )


# ── Token purchase (in-chat Yoco checkout) ────────────────────────────────────


def _pack_tokens_with_bonus(pkg: dict, bonus_eligible: bool) -> int:
    """Tokens this buyer actually receives, first-purchase bonus included."""
    tokens = int(pkg["tokens"])
    bonus = settings.FIRST_PURCHASE_BONUS_TOKENS
    if bonus_eligible and bonus > 0 and tokens >= settings.FIRST_PURCHASE_BONUS_MIN_TOKENS:
        return tokens + bonus
    return tokens


def _pack_rate(pkg: dict, bonus_eligible: bool = False) -> float:
    return float(pkg["price"]) / _pack_tokens_with_bonus(pkg, bonus_eligible)


def _per_token_label(pkg: dict, bonus_eligible: bool = False) -> str:
    """"R13/token", or the true rate once the first-purchase bonus is applied.

    The website priced packs with the bonus included and WhatsApp did not, so
    the pack that is actually cheapest per run looked worse in chat than on the
    site — to exactly the buyers the bonus exists to convert.
    """
    rate = _pack_rate(pkg, bonus_eligible)
    rate_str = f"{rate:.2f}".rstrip("0").rstrip(".")
    if _pack_tokens_with_bonus(pkg, bonus_eligible) != int(pkg["tokens"]):
        return f"R{rate_str}/token with bonus"
    return f"R{rate_str}/token"


async def _send_token_pack_picker(phone: str, db: Session) -> None:
    """Let the user pick a token pack right in the chat.

    Selecting a pack replies with a direct Yoco payment link — no website
    login needed. Falls back to the old magic-link flow when Yoco isn't
    configured (e.g. local dev).
    """
    bal = get_credit_balance(db, phone)
    w = "token" if bal == 1 else "tokens"
    record_server_event(phone, "pack_picker_shown", "whatsapp")

    if not payments.yoco_configured():
        link = _make_magic_link(phone, db, redirect_to="/subscription")
        pack_lines = []
        for p in settings.TOKEN_PACKAGES:
            price = f"{float(p['price']):g}"
            badge = f" — _{p['badge']}_" if p.get("badge") else ""
            pack_lines.append(f"• *{int(p['tokens'])} tokens* — R{price}{badge}")
        await _send_whatsapp_cta_url(
            phone,
            header="Buy Tokens 🪙",
            body=(
                f"Your balance: *{bal} {w}*\n\n"
                f"Token packs available:\n" + "\n".join(pack_lines)
            ),
            button_text="Buy on website",
            url_link=link,
            footer=_link_expiry_note().strip("_"),
        )
        return

    bonus = settings.FIRST_PURCHASE_BONUS_TOKENS
    bonus_min = settings.FIRST_PURCHASE_BONUS_MIN_TOKENS
    bonus_eligible = bonus > 0 and _is_first_purchase(db, phone)
    bonus_line = ""
    if bonus_eligible:
        bonus_line = (
            f"🎁 First purchase? You get *+{bonus} bonus tokens* on any pack of "
            f"{bonus_min}+ tokens.\n\n"
        )

    # Value anchor: point at the pack that is genuinely cheapest per match run
    # *for this buyer* — with the first-purchase bonus counted, that is not
    # always the one wearing the "Most Popular" badge, and anchoring on a pack
    # the list itself shows to be worse reads as a sales trick.
    anchor_line = ""
    best = min(
        settings.TOKEN_PACKAGES,
        key=lambda p: _pack_rate(p, bonus_eligible),
        default=None,
    )
    if best:
        best_price = f"{float(best['price']):g}"
        rate_str = f"{_pack_rate(best, bonus_eligible):.2f}".rstrip("0").rstrip(".")
        with_bonus = _pack_tokens_with_bonus(best, bonus_eligible)
        bonus_bit = f" (+{bonus} bonus = {with_bonus})" if with_bonus != int(best["tokens"]) else ""
        anchor_line = (
            f"💡 Best value for you: the *{int(best['tokens'])}-token pack (R{best_price})*{bonus_bit} — "
            f"about R{rate_str} per match run.\n\n"
        )

    rows = []
    for p in settings.TOKEN_PACKAGES:
        price = f"{float(p['price']):g}"
        desc = _per_token_label(p, bonus_eligible)
        if p.get("badge"):
            desc = f"{p['badge']} · {desc}"
        rows.append({
            "id": f"buy_{int(p['tokens'])}",
            "title": f"{int(p['tokens'])} tokens — R{price}"[:24],
            "description": desc[:72],
        })

    await _send_whatsapp_list(
        phone,
        header="Buy Tokens 🪙",
        body=(
            f"Your balance: *{bal} {w}*\n\n"
            f"{bonus_line}"
            f"{anchor_line}"
            "1 token = 1 *Find Matches* run. Pick a pack and I'll send you a "
            "secure payment link — tokens are added the moment you pay."
        ),
        footer="Secure payment via Yoco · No recurring charges",
        button="Choose a pack",
        rows=rows,
        section_title="Token packs",
    )


async def _start_whatsapp_checkout(phone: str, tokens: int, db: Session) -> None:
    """Create a Yoco checkout for this user and drop the payment link in chat."""
    pkg = payments.find_package(tokens)
    if pkg is None:
        await _send_token_pack_picker(phone, db)
        return

    bonus = settings.FIRST_PURCHASE_BONUS_TOKENS
    first = (
        bonus > 0
        and tokens >= settings.FIRST_PURCHASE_BONUS_MIN_TOKENS
        and _is_first_purchase(db, phone)
    )

    try:
        pay_url = await payments.create_checkout(db, phone, tokens, channel="whatsapp")
    except payments.CheckoutError:
        link = _make_magic_link(phone, db, redirect_to="/subscription")
        await _send_whatsapp_cta_url(
            phone,
            body="⚠️ I couldn't start the payment just now. You can buy on the website instead:",
            button_text="Buy on website",
            url_link=link,
            footer=_link_expiry_note().strip("_"),
        )
        return

    price = f"{float(pkg['price']):g}"
    bonus_line = f"🎁 Includes *+{bonus} bonus tokens* — first-purchase gift.\n" if first else ""
    # The CTA button opens inside WhatsApp's webview, where a 3-D Secure
    # hand-off to the buyer's banking app has nowhere to come back to and the
    # payment dies with no error. The plain URL below is the escape hatch:
    # long-pressing it offers "Open in browser", which survives the redirect.
    # (Apple Pay / Google Pay are unavailable in that webview — never promise them.)
    await _send_whatsapp_cta_url(
        phone,
        body=(
            f"🪙 *{pkg['label']} Pack — {tokens} tokens for R{price}*\n"
            f"{bonus_line}\n"
            "Pay by card (takes ~1 min). "
            "Tokens are added automatically — I'll confirm here the moment your payment lands. ⚡\n\n"
            f"_If payment doesn't open properly: tap and hold the link below, then 'Open in browser'_ — {pay_url}"
        ),
        button_text="Pay now 💳",
        url_link=pay_url,
        footer="Secure payment via Yoco",
    )


# ── AI helpers ────────────────────────────────────────────────────────────────

# Kept deliberately short: every extra required question costs real signups
# (a third of early users abandoned the old 13-field interrogation, and the
# 7-field version still leaked people). Four questions is the minimum the
# matching engine needs to produce a credible first run; everything else is
# captured when volunteered, nudged post-first-match (certifications), or
# added later via *edit profile*.
REQUIRED_ONBOARD_FIELDS = [
    "firstName", "desiredRole", "currentLocation", "yearsExperience",
]

# Nice-to-have fields — recorded when the user volunteers them, never asked
# during onboarding. Sharpen matching once present.
OPTIONAL_ONBOARD_FIELDS = [
    "lastName", "nationality", "certifications",
    "sex", "preferredLocations", "contractType", "salaryMin", "salaryMax", "languages",
]

_FIELD_LABELS: dict[str, str] = {
    "firstName": "name",
    "lastName": "name",
    "sex": "gender",
    "desiredRole": "dream role",
    "yearsExperience": "experience",
    "nationality": "nationality",
    "currentLocation": "where you're based",
    "preferredLocations": "preferred cruising grounds",
    "contractType": "contract preference",
    "salaryMin": "salary range",
    "salaryMax": "salary range",
    "certifications": "certs & tickets",
    "languages": "languages",
}

_FIELD_QUESTIONS: dict[str, str] = {
    "firstName": "First things first — what's your full name? 🪪",
    "lastName": "And your surname? 🪪",
    "sex": "How should we list your gender? (Male, Female, Other, or Prefer not to say)",
    "desiredRole": "What's your dream role on board? ⚓ (e.g. Chief Stew, Bosun, Engineer, Chef, Deckhand…)",
    "yearsExperience": "How many years have you been in yachting or maritime? Even a rough number works! 🕐",
    "nationality": "What's your nationality? 🌍",
    "currentLocation": "Where are you based right now? City & country 📍",
    "preferredLocations": "Which cruising grounds are you keen on? 🗺️ (Med, Caribbean, PNW, Middle East, etc.)",
    "contractType": "What kind of contract suits you best — *Permanent*, *Seasonal*, *Rotational*, or *Temporary*? 📋",
    "salaryMin": "What's your monthly salary range in EUR? 💰 (e.g. 3000–5000)",
    "salaryMax": "And the top end of your salary range in EUR? 💰",
    "certifications": "What certs & tickets do you hold? 🏅 (STCW, ENG1, Yachtmaster, PYA, etc. — or just say 'none yet')",
    "languages": "Last one — what languages do you speak? 🗣️",
}


def _build_onboard_system(profile: dict) -> str:
    missing = [f for f in REQUIRED_ONBOARD_FIELDS if not str(profile.get(f, "")).strip()]
    all_done = len(missing) == 0
    filled = len(REQUIRED_ONBOARD_FIELDS) - len(missing)
    seen_labels: set[str] = set()
    readable_missing: list[str] = []
    for f in missing:
        label = _FIELD_LABELS.get(f, f)
        if label not in seen_labels:
            seen_labels.add(label)
            readable_missing.append(label)
    missing_text = ", ".join(readable_missing) if readable_missing else "none — all fields collected!"
    next_field = _missing_onboard_fields(profile)[0] if missing else ""
    next_question = _onboard_question(next_field) if next_field else ""
    return f"""You are the profile EXTRACTOR behind CARVER, a superyacht crew agent on WhatsApp.

You do not run the conversation. The bot asks a fixed sequence of questions in
code and writes its own replies — your only job is to read the user's latest
message and pull structured profile fields out of it. Your "message" field is
ignored, so do not waste effort on it.

Profile so far ({filled}/{len(REQUIRED_ONBOARD_FIELDS)} required fields):
{json.dumps(profile, ensure_ascii=True)}

Still missing: {missing_text}

The question the user is answering right now is:
  [{next_field or "none"}] {next_question or "(profile complete)"}

So their message is almost certainly that field's answer — map it there unless
it clearly says something else. If they volunteer extra info (surname,
nationality, certifications, salary range, contract type, preferred cruising
grounds, languages, gender), capture that in "updates" too.
NEVER mention tokens, prices, buying or topping up anywhere in your output.

Data rules:
- Only populate update fields when the user clearly provided that info.
- Do not invent or assume any facts. An unparseable message means empty updates.
- Keep values short and clean (e.g. nationality: "British", contractType: "Seasonal").
- For salaryMin/salaryMax use numeric strings only (e.g. "4000", "6000").
- If the user wants to skip a field, set it to "unknown" so it counts as filled.

Return strict JSON only:
{{"message": "", "done": {str(all_done).lower()}, "updates": {{"firstName": "", "lastName": "", "sex": "", "desiredRole": "", "yearsExperience": "", "nationality": "", "currentLocation": "", "preferredLocations": "", "contractType": "", "salaryMin": "", "salaryMax": "", "certifications": "", "languages": ""}}}}

For "sex", ONLY use one of: "male", "female", "other", "prefer_not_to_say". Map the user's answer to the closest value."""


def _build_interview_system(profile: dict) -> str:
    return f"""You are CARVER — a sharp, friendly crew agent on WhatsApp who knows the superyacht industry inside out.
You're doing a quick interview to fine-tune this crew member's preferences so the matching engine can find them the best gigs.

Current profile:
{json.dumps(profile, ensure_ascii=True)}

Review conversation history carefully. NEVER repeat questions already covered.

Style:
- WhatsApp-native: punchy messages, *bold* for emphasis, 1-2 emojis per message.
- React to answers naturally ("Love it!", "Good to know.") before your next question.
- Use yachting lingo (charter season, cruising grounds, rotation, vessel, galley, bridge, etc.).
- Keep it conversational — 2-3 sentences max.

Return strict JSON only:
{{"message": "your reply", "updates": {{"sex": "", "desiredRole": "", "preferredLocations": "", "contractType": "", "rotationPreference": "", "availableFrom": "", "salaryMin": "", "salaryMax": "", "languages": "", "certifications": "", "bio": ""}}}}

Rules:
- Only fill update fields if the user clearly provided that info.
- Keep values short and clean.
- Do not invent personal facts.
- For "sex", ONLY use one of: "male", "female", "other", "prefer_not_to_say". Map the user's answer to the closest value.
- If the user's gender/sex is not yet in their profile, ask about it early in the conversation."""


def _extract_json(text: str) -> dict:
    import re
    raw = (text or "").strip()
    raw = re.sub(r"^```json\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^```", "", raw)
    raw = re.sub(r"```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def _fallback_extract(partial: dict, user_message: str) -> dict:
    """Best-effort field extraction when the LLM call fails entirely."""
    import re
    updates: dict[str, str] = {}
    text = user_message.strip()
    if not text:
        return updates

    # Deterministic question order (role first) — must agree with what the user
    # was actually just asked, or the answer lands in the wrong field.
    missing = _missing_onboard_fields(partial)
    if not missing:
        return updates

    first_missing = missing[0]

    if first_missing in ("firstName", "lastName"):
        parts = text.split()
        if 1 <= len(parts) <= 4 and all(p.isalpha() or p == "-" for p in parts):
            updates["firstName"] = parts[0].title()
            if len(parts) > 1:
                updates["lastName"] = " ".join(parts[1:]).title()

    elif first_missing == "sex":
        low = text.lower().strip()
        for val in ("male", "female", "other"):
            if val in low:
                updates["sex"] = val
                break
        if not updates and ("prefer" in low or "skip" in low or "rather not" in low):
            updates["sex"] = "prefer_not_to_say"

    elif first_missing == "yearsExperience":
        m = re.search(r"(\d{1,2})", text)
        if m:
            updates["yearsExperience"] = m.group(1)

    elif first_missing in ("salaryMin", "salaryMax"):
        nums = re.findall(r"(\d[\d,.]*)", text.replace(" ", ""))
        clean = [n.replace(",", "").replace(".", "") for n in nums]
        clean = [n for n in clean if n.isdigit() and 500 <= int(n) <= 100000]
        if len(clean) >= 2:
            vals = sorted(int(n) for n in clean[:2])
            updates["salaryMin"] = str(vals[0])
            updates["salaryMax"] = str(vals[1])
        elif len(clean) == 1:
            updates["salaryMin"] = clean[0]

    elif first_missing == "desiredRole":
        if len(text) <= 60:
            updates["desiredRole"] = text.title()

    elif first_missing == "nationality":
        if len(text) <= 40:
            updates["nationality"] = text.title()

    elif first_missing == "currentLocation":
        if len(text) <= 60:
            updates["currentLocation"] = text.title()

    elif first_missing == "preferredLocations":
        if len(text) <= 100:
            updates["preferredLocations"] = text

    elif first_missing == "contractType":
        low = text.lower()
        for ct in ("permanent", "seasonal", "rotational", "temporary"):
            if ct in low:
                updates["contractType"] = ct.title()
                break
        if not updates and len(text) <= 30:
            updates["contractType"] = text.title()

    elif first_missing == "certifications":
        if len(text) <= 200:
            updates["certifications"] = text

    elif first_missing == "languages":
        if len(text) <= 200:
            updates["languages"] = text

    return updates


async def _call_openai(system: str, history: list, user_message: str, *, model: str | None = None) -> dict:
    """Call OpenAI and return parsed JSON dict."""
    messages = [{"role": "system", "content": system}]
    for msg in history[-16:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message or "Begin."})

    model = model or settings.WHATSAPP_AI_MODEL
    _gpt5 = "gpt-5" in model
    payload: dict = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max(2000, 4096) if _gpt5 else 500,
        "response_format": {"type": "json_object"},
    }
    if not _gpt5:
        payload["temperature"] = 0.5

    # Never raise: every caller is on the WhatsApp hot path, where an
    # unhandled timeout or malformed body means the user's message is answered
    # by nothing at all. An empty dict is the "LLM failed" signal callers
    # already understand, and they each have a non-AI fallback.
    try:
        resp = await _http.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json=payload,
            timeout=25.0,
        )
        if resp.status_code >= 400:
            log.error("OpenAI error | status=%d | body=%s", resp.status_code, resp.text[:300])
            return {}
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return {}
        text = ((choices[0].get("message") or {}).get("content") or "").strip()
        if not text:
            log.error("OpenAI empty content | finish=%s | model=%s",
                      choices[0].get("finish_reason", "?"), model)
            return {}
        return _extract_json(text)
    except Exception as exc:
        log.exception("OpenAI call failed | model=%s | %s", model, exc)
        return {}


# ── Profile helpers ───────────────────────────────────────────────────────────

def _apply_updates(partial: dict, updates: dict) -> dict:
    """Merge non-empty AI updates into the partial profile dict."""
    for k, v in updates.items():
        if isinstance(v, str) and v.strip():
            partial[k] = v.strip()
    return partial


def _record_onboard_fields(phone_number: str, before: dict, after: dict) -> None:
    """One durable event per onboarding field, the first time it is captured.

    Question-by-question drop-off is invisible from `onboard_started` /
    `onboard_completed` alone — this is what shows *which* question loses people.
    Re-answering a field never fires again, so counts stay comparable.
    """
    for field, value in after.items():
        if field.startswith("_"):          # _retryField / _retryCount bookkeeping
            continue
        if str(before.get(field, "")).strip():
            continue
        if not str(value or "").strip():
            continue
        record_server_event(phone_number, "onboard_field_filled", field)


def _save_profile_to_db(phone_number: str, partial: dict, db: Session) -> None:
    """Upsert CrewProfile from the WhatsApp partial profile dict."""
    existing = db.query(CrewProfile).filter(CrewProfile.user_key == phone_number).first()
    field_map = {
        "firstName": "first_name", "lastName": "last_name", "sex": "sex",
        "desiredRole": "desired_role", "yearsExperience": "years_experience",
        "nationality": "nationality", "currentLocation": "current_location",
        "preferredLocations": "preferred_locations", "contractType": "contract_type",
        "salaryMin": "salary_min", "salaryMax": "salary_max",
        "certifications": "certifications", "languages": "languages",
        "rotationPreference": "rotation_preference", "availableFrom": "available_from",
        "bio": "bio",
    }
    if existing:
        for src, dst in field_map.items():
            if src in partial:
                setattr(existing, dst, partial[src])
        db.commit()
    else:
        import secrets as _secrets
        slug = _secrets.token_urlsafe(6)
        while db.query(CrewProfile).filter(CrewProfile.profile_slug == slug).first():
            slug = _secrets.token_urlsafe(6)
        kwargs = {dst: partial[src] for src, dst in field_map.items() if src in partial}
        profile = CrewProfile(user_key=phone_number, profile_slug=slug, **kwargs)
        db.add(profile)
        db.commit()


# ── Public crew profile link ─────────────────────────────────────────────────
# Every crew profile already has a slug and a public page — it was only ever
# surfaced inside AI-drafted application emails, so users never knew they had
# a shareable card. One link makes the profile worth completing.

def _ensure_profile_slug(db: Session, profile: CrewProfile) -> str:
    """The profile's slug, minting one first if a legacy row is missing it."""
    if profile.profile_slug:
        return profile.profile_slug
    from app.routes.profile import _generate_slug

    slug = _generate_slug()
    while db.query(CrewProfile).filter(CrewProfile.profile_slug == slug).first():
        slug = _generate_slug()
    profile.profile_slug = slug
    db.commit()
    return slug


def _public_profile_url(db: Session, profile: CrewProfile) -> str:
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}/crew/{_ensure_profile_slug(db, profile)}"


# ── Command handlers ──────────────────────────────────────────────────────────

async def _handle_profile_command(phone_number: str, db: Session) -> str:
    profile = db.query(CrewProfile).filter(CrewProfile.user_key == phone_number).first()
    bal = get_credit_balance(db, phone_number)
    tok_w = "token" if bal == 1 else "tokens"
    if crew_match_free():
        token_line = f"\n\n💳 *Tokens:* {bal} {tok_w} — *Find Matches* runs are free right now."
    else:
        token_line = f"\n\n💳 *Tokens:* {bal} {tok_w} — each *Find Matches* uses 1; *buy tokens* to top up or submit a job to earn 1."
    if not profile:
        return (
            "👋 *Welcome aboard CARVER!*\n\n"
            "You don't have a crew profile yet. Tap *Edit Profile* to set one up — "
            "quick and easy, then you're ready to match with superyacht roles."
            + token_line
        )
    name = f"{profile.first_name or ''} {profile.last_name or ''}".strip()
    lines = [f"🪪 *{name or 'Your Crew Profile'}*\n"]
    if profile.desired_role:
        lines.append(f"⚓ *Role:* {profile.desired_role}")
    if profile.nationality or profile.current_location:
        loc_parts = filter(None, [profile.nationality, profile.current_location])
        lines.append(f"🌍 *Location:* {' · '.join(loc_parts)}")
    if profile.preferred_locations:
        lines.append(f"📍 *Preferred:* {profile.preferred_locations}")
    if profile.contract_type:
        lines.append(f"📋 *Contract:* {profile.contract_type}")
    if profile.years_experience:
        lines.append(f"🕐 *Experience:* {profile.years_experience} years")
    if profile.certifications:
        lines.append(f"🏅 *Certs:* {profile.certifications}")
    if profile.languages:
        lines.append(f"🗣 *Languages:* {profile.languages}")
    if profile.salary_min or profile.salary_max:
        lo = f"€{int(profile.salary_min)}" if profile.salary_min else ""
        hi = f"€{int(profile.salary_max)}" if profile.salary_max else ""
        salary_str = f"{lo}–{hi}" if lo and hi else lo or hi
        lines.append(f"💰 *Salary:* {salary_str}/mo")
    if profile.available_from:
        lines.append(f"📅 *Available:* {profile.available_from}")
    lines.append(f"\n🔗 *Your public profile:* {_public_profile_url(db, profile)}\n_Send it to a captain or recruiter — no login needed to view it._")
    lines.append(token_line.strip())
    return "\n".join(lines)


async def _handle_docs_command(phone_number: str, db: Session) -> str:
    docs = db.query(Document).filter(Document.user_key == phone_number).all()
    uploaded = {d.doc_type for d in docs}
    all_types = ["cv", "references", "passport", "stcw", "eng1", "photo"]
    labels = {"cv": "CV / Résumé", "references": "References", "passport": "Passport",
               "stcw": "STCW", "eng1": "ENG1 Medical", "photo": "Profile Photo"}
    lines = ["📁 *Your Crew Documents*\n"]
    for dt in all_types:
        mark = "✅" if dt in uploaded else "❌"
        lines.append(f"{mark} {labels.get(dt, dt.upper())}")
    done = len(uploaded)
    lines.append(f"\n_Uploaded {done} of {len(all_types)} — recruiters love a complete file._")
    return "\n".join(lines)


async def _handle_jobs_command(phone_number: str, db: Session) -> None:
    link = _make_magic_link(phone_number, db, redirect_to="/jobs")
    await _send_whatsapp_cta_url(
        phone_number,
        header="Browse Open Yacht Positions 🔎",
        body="View all live superyacht crew roles — deck, interior, engineering & more.",
        button_text="Browse jobs",
        url_link=link,
        footer=_link_expiry_note().strip("_"),
    )


def _normalise_match_scope(match_scope: str | None) -> str:
    return _MATCH_SCOPE_RECENT if match_scope == _MATCH_SCOPE_RECENT else _MATCH_SCOPE_ALL


# ── Save / dismiss interactions ──────────────────────────────────────────────

def _dismissed_job_ids(db: Session, user_key: str) -> set[int]:
    """Job ids this user has dismissed — excluded from future match runs."""
    rows = (
        db.query(MatchInteraction.job_id)
        .filter(
            MatchInteraction.user_key == user_key,
            MatchInteraction.action == "dismissed",
        )
        .all()
    )
    return {r[0] for r in rows}


def _record_match_interaction(db: Session, user_key: str, job_id: int, action: str) -> None:
    """Idempotent upsert of a saved/dismissed row — repeated taps are no-ops."""
    existing = (
        db.query(MatchInteraction.id)
        .filter(
            MatchInteraction.user_key == user_key,
            MatchInteraction.job_id == job_id,
            MatchInteraction.action == action,
        )
        .first()
    )
    if existing is not None:
        return
    try:
        db.add(MatchInteraction(user_key=user_key, job_id=job_id, action=action))
        db.commit()
    except Exception:
        # Unique constraint race (double-tap) — the row is there, which is all we need.
        db.rollback()


async def _send_paywall_teaser(phone_number: str, db: Session, profile, all_jobs: list) -> None:
    """Zero-token paywall — sell at the moment of desire.

    Instead of a flat refusal, show the user what's actually waiting for them:
    a cheap role-substring count of open jobs fitting their desired role (no
    LLM spend), with a couple of real positions named, locked behind the run.
    Falls back to the plain message when nothing matches.
    """
    from app.services.job_alerts import _matching_jobs

    current_credits = get_credit_balance(db, phone_number)
    teasers = _matching_jobs(all_jobs, (profile.desired_role or "") if profile else "")
    # Never tease a job the user already said "not for me" to (cheap belt-and-
    # braces — the match query upstream excludes them too).
    dismissed = _dismissed_job_ids(db, phone_number)
    if dismissed:
        teasers = [j for j in teasers if j.id not in dismissed]

    cheapest = min(settings.TOKEN_PACKAGES, key=lambda p: float(p["price"]))
    cheapest_price = f"{float(cheapest['price']):g}"

    if teasers:
        n = len(teasers)
        lines = []
        for job in teasers[:2]:
            bits = [job.role or job.title]
            if job.yacht_length_m:
                bits.append(f"{job.yacht_length_m}m")
            if job.location:
                bits.append(job.location)
            lines.append("  🔒 " + " · ".join(str(b) for b in bits if b))
        more = n - len(lines)
        more_line = f"  🔒 …and *{more} more*\n" if more > 0 else ""
        await _send_whatsapp(
            phone_number,
            f"👀 *{n} open position{'s' if n != 1 else ''}* in the database right now "
            f"look like a fit for your *{profile.desired_role}* profile:\n\n"
            + "\n".join(lines) + ("\n" + more_line if more_line else "\n")
            + "\nA full AI match run ranks every one against your profile and drafts "
            "your application emails — it takes *1 token*, and you're at "
            f"*{current_credits}*.\n\n"
            f"Packs start at *R{cheapest_price}*. Or submit a job you've seen posted "
            "to earn a free token.",
        )
        record_server_event(phone_number, "paywall_teaser_shown", str(n))
    else:
        await _send_whatsapp(
            phone_number,
            "⚠️ You need *1 token* to run matching.\n\n"
            f"Packs start at *R{cheapest_price}* — type *buy tokens* to top up, "
            "or submit a job to earn a free token.\n"
            f"Current balance: *{current_credits}* token{'s' if current_credits != 1 else ''}.",
        )
    await _send_whatsapp_buttons(
        phone_number,
        "Unlock your matches?" if teasers else "What would you like to do?",
        [("cmd_subscribe", "Buy Tokens"), ("btn_submit_job", "Submit Job"), ("btn_menu", "Menu")],
    )


# ── Honest result framing ─────────────────────────────────────────────────────
# The engine grades every result into a tier (strong ≥75, good ≥50, stretch
# 30-49 — and stretch no longer clears MATCH_THRESHOLD, so it is never sold as
# a match). Both helpers degrade to something true when the attributes are
# missing, so an older engine build never breaks the reply.

_TIER_WORDS = {"strong": "strong", "good": "good", "stretch": "a stretch"}


def _tier_label(tier: str, compatibility: float = 0.0) -> str:
    """User-facing word for a result tier; '' when unknown."""
    tier = (tier or "").strip().lower()
    if not tier:
        try:
            from app.services.matching_engine import tier_for
            tier = tier_for(float(compatibility or 0.0))
        except Exception:
            return ""
    return _TIER_WORDS.get(tier, "")


def _match_summary_header(results, matched_count: int) -> str:
    """"3 strong · 6 good fits" when the engine graded the run, else a count.

    Never an exclamation mark, never a number the top three can contradict.
    """
    counts = getattr(results, "tier_counts", None)
    if isinstance(counts, dict):
        parts = []
        for name in ("strong", "good"):
            n = int(counts.get(name) or 0)
            if n:
                parts.append(f"{n} {name}")
        if parts:
            total = sum(int(counts.get(k) or 0) for k in ("strong", "good"))
            return f"🎯 *{' · '.join(parts)} fit{'s' if total != 1 else ''}* — top 3:"
    return f"🎯 *{matched_count} job{'s' if matched_count != 1 else ''} ranked* — top 3:"


async def _handle_match_command(phone_number: str, db: Session, match_scope: str = _MATCH_SCOPE_ALL) -> None:
    """Run the AI matching engine, save results, and send a website link.

    Results are persisted as a MatchSession so the user can view all matches
    and draft application emails on the website.
    """
    import math as _math

    from app.services.matching_engine import (
        BATCH_SIZE,
        MAX_WORKERS,
        PREFILTER_TOP_N,
        CandidateProfile,
        match_candidate_to_jobs,
    )
    # Imported lazily: crew_match never imports whatsapp, so there is no cycle,
    # but keeping it local matches the other heavy imports in this handler.
    from app.routes.crew_match import _job_to_summary

    profile = db.query(CrewProfile).filter(CrewProfile.user_key == phone_number).first()
    if not profile:
        await _send_whatsapp(
            phone_number,
            "You don't have a crew profile yet — set one up first so we can match you to yacht roles.",
        )
        await _send_whatsapp_buttons(
            phone_number,
            "Ready to get started?",
            [("btn_edit_profile", "Edit Profile"), ("btn_help", "Help")],
        )
        return

    if not settings.OPENAI_API_KEY:
        await _send_whatsapp(phone_number, "⚠️ Matching engine is temporarily unavailable. Try again soon.")
        return

    match_scope = _normalise_match_scope(match_scope)
    # Dismissals shape future runs — never re-scan a job the user said no to.
    dismissed_ids = _dismissed_job_ids(db, phone_number)
    recent_days = max(1, settings.WA_MATCH_RECENT_DAYS)

    def _open_jobs(*, recent: bool) -> list[Job]:
        q = db.query(Job).filter(Job.status.in_(["open", "priority"]))
        if dismissed_ids:
            q = q.filter(Job.id.notin_(dismissed_ids))
        if recent:
            q = q.filter(Job.created_at >= datetime.now(timezone.utc) - timedelta(days=recent_days))
        return q.order_by(Job.created_at.desc()).all()

    widen_note = ""
    if match_scope == _MATCH_SCOPE_RECENT:
        all_jobs = _open_jobs(recent=True)
        scope_label = f"recent posts from the last {recent_days} day{'s' if recent_days != 1 else ''}"
        # Freshness by default, but never at the price of an empty run: a thin
        # week silently widens to the whole open board and says so in one line.
        if len(all_jobs) < _MATCH_MIN_RECENT_RESULTS:
            narrow_count = len(all_jobs)
            wide_jobs = _open_jobs(recent=False)
            if len(wide_jobs) > narrow_count:
                all_jobs = wide_jobs
                match_scope = _MATCH_SCOPE_ALL
                scope_label = "all open jobs"
                widen_note = f"Only {narrow_count} this week, so I widened to the last month."
    else:
        all_jobs = _open_jobs(recent=False)
        scope_label = "all database jobs"

    if not all_jobs:
        await _send_whatsapp(
            phone_number,
            "No open yacht positions are on the board right now — I'll ping you the moment fresh ones land.",
        )
        return

    # CREW_MATCH_FREE: the run costs nothing and can never be refused. The
    # balance is still read so it keeps appearing where it already did.
    free_run = crew_match_free()
    if free_run:
        credits_remaining = get_credit_balance(db, phone_number)
    else:
        credits_remaining = spend_credits(db, phone_number, amount=1)
        if credits_remaining is None:
            record_server_event(phone_number, "paywall_hit", "whatsapp")
            await _send_paywall_teaser(phone_number, db, profile, all_jobs)
            return

    _AVG_SECS_PER_BATCH = 8
    scored_jobs = min(len(all_jobs), PREFILTER_TOP_N)
    num_batches = _math.ceil(scored_jobs / BATCH_SIZE)
    batch_waves = _math.ceil(num_batches / MAX_WORKERS)
    est_secs = max(batch_waves * _AVG_SECS_PER_BATCH, _AVG_SECS_PER_BATCH)
    est_str = f"~{est_secs}s" if est_secs < 60 else f"~{round(est_secs / 60)} min"

    tok_left = "token" if credits_remaining == 1 else "tokens"
    spend_note = (
        "🎁 *This run is free.*\n\n" if free_run
        else f"💳 *1 token used* — *{credits_remaining}* {tok_left} left.\n\n"
    )
    await _send_whatsapp(
        phone_number,
        spend_note
        + (widen_note + "\n\n" if widen_note else "")
        + f"⏳ Ranking *{len(all_jobs)} positions* from *{scope_label}* against your profile ({est_str}) — hang tight.",
    )

    certs = [c.strip() for c in (profile.certifications or "").replace("\n", ",").split(",") if c.strip()]
    langs = [lang.strip() for lang in (profile.languages or "").split(",") if lang.strip()]

    job_history_entries = (
        db.query(JobHistoryEntry)
        .filter(JobHistoryEntry.user_key == phone_number)
        .order_by(JobHistoryEntry.start_date.desc())
        .limit(10)
        .all()
    )
    jh = [
        {"role": e.role, "yacht": e.yacht_name, "yacht_type": e.yacht_type or "",
         "start_date": e.start_date or "", "end_date": e.end_date or "",
         "description": (e.description or "")[:200]}
        for e in job_history_entries
    ]

    doc_parts = []
    for d in db.query(Document).filter(Document.user_key == phone_number, Document.scanned_text.isnot(None)).all():
        if d.scanned_text:
            doc_parts.append(f"[{d.doc_type.upper()}] {d.scanned_text}")
    doc_summary = "\n\n".join(doc_parts)

    candidate = CandidateProfile(
        user_key=phone_number,
        first_name=profile.first_name or "",
        last_name=profile.last_name or "",
        sex=profile.sex or "",
        desired_role=profile.desired_role or "",
        location=profile.current_location or "",
        preferred_locations=profile.preferred_locations or "",
        nationality=profile.nationality or "",
        years_experience=profile.years_experience or "",
        salary_min=profile.salary_min or "",
        salary_max=profile.salary_max or "",
        contract_type=profile.contract_type or "",
        rotation_preference=profile.rotation_preference or "",
        available_from=profile.available_from or "",
        certifications=certs,
        languages=langs,
        bio=profile.bio or "",
        job_history=jh,
        document_summary=doc_summary,
    )

    # Parity with the web path. The old inline literal here dropped created_at,
    # requirements, responsibilities, urgent_hire, minimum_license and
    # rank_level — which killed recency scoring on WhatsApp outright and handed
    # the LLM a thinner record than routes/crew_match.py builds. One helper, one
    # record shape, both channels.
    job_summaries = [_job_to_summary(j) for j in all_jobs]
    jobs_by_id = {j.id: j for j in all_jobs}

    try:
        results = await asyncio.to_thread(
            match_candidate_to_jobs,
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_MODEL,
            candidate=candidate,
            jobs=job_summaries,
        )
    except Exception as exc:
        log.error("WhatsApp match engine error | %s", exc)
        # Nothing was charged for a free run, so there is nothing to refund —
        # and promising a refund that never happens is worse than saying less.
        if free_run:
            snag = "⚠️ Matching hit a snag. Try again in a moment?"
        else:
            credits_remaining = add_credits(db, phone_number, amount=1)
            snag = "⚠️ Matching hit a snag — your token was refunded. Try again in a moment?"
        await _send_whatsapp_buttons(
            phone_number,
            snag,
            [("btn_find_matches", "Try Again"), ("btn_menu", "Menu")],
        )
        return

    matched = [r for r in (results or []) if r.matched]
    if not matched:
        # A run that surfaces nothing delivered nothing — the user does not pay
        # for it. add_credits is the refund path (same as the engine-error
        # branch above) and returns the new balance.
        if not free_run:
            credits_remaining = add_credits(db, phone_number, amount=1)
        record_server_event(phone_number, "match_zero_refund", str(len(all_jobs)))
        bal_w = "token" if credits_remaining == 1 else "tokens"
        ranked = (
            f"I ranked {len(all_jobs)} live position{'s' if len(all_jobs) != 1 else ''} "
            "and none of them clear the bar for you right now"
        )
        await _send_whatsapp(
            phone_number,
            (
                f"{ranked}.\n\n" if free_run else
                f"{ranked} — so I've put your token back. "
                f"You're at *{credits_remaining}* {bal_w}.\n\n"
            )
            + "Certs, preferred cruising grounds and a salary range usually turn "
            "this around on the next run.",
        )
        await _send_whatsapp_buttons(
            phone_number,
            "Want to improve your match rate?",
            [("btn_edit_profile", "Edit Profile"), ("btn_upload_docs", "Upload Docs"), ("btn_menu", "Menu")],
        )
        return

    # Persist results as a MatchSession for the website
    match_session = MatchSession(
        user_key=phone_number,
        status="completed",
        total_jobs_scanned=len(all_jobs),
        total_matched=len(matched),
        completed_at=datetime.now(timezone.utc),
    )
    db.add(match_session)
    db.flush()
    for r in matched:
        db.add(MatchSessionResult(
            session_id=match_session.id,
            job_id=r.job_id,
            matched=r.matched,
            compatibility=r.compatibility,
            reason=r.reason,
            strengths=json.dumps(r.strengths),
            gaps=json.dumps(r.gaps),
            factor_scores=json.dumps(r.factor_scores),
        ))
    db.commit()
    metrics.increment("crew_matches")
    record_server_event(phone_number, "match_completed", str(len(matched)))

    # Remember this session so bare digit replies ("1", "2", …) can drill into
    # a result without leaving the chat.
    wa_session = db.query(WhatsAppSession).filter(WhatsAppSession.phone_number == phone_number).first()
    if wa_session:
        wa_session.last_match_session_id = match_session.id
        _clear_saved_list_context(wa_session)  # digit replies now target the fresh run
        db.commit()

    # Build brief summary for WhatsApp (top 3).
    #
    # "Found 35 matches!" was the single most dishonest line in the product —
    # it hyped a number the user could see was mostly irrelevant the moment
    # they read the top three. Lead with what the engine actually concluded.
    top = matched[:3]
    lines = [_match_summary_header(results, len(matched)) + "\n"]
    lines.append(f"_Scanned {scope_label}._\n")
    for i, m in enumerate(top, 1):
        job = jobs_by_id.get(m.job_id)
        if not job:
            continue
        compat = int(m.compatibility)
        tier = _tier_label(getattr(m, "tier", "") or "", m.compatibility)
        tier_bit = f" · {tier}" if tier else ""
        lines.append(f"{i}. *{job.title}* — {job.location} ({compat}%{tier_bit})")
    if len(matched) > 3:
        lines.append(f"   _...and {len(matched) - 3} more_")

    digits = " or ".join(f"*{i}*" for i in range(1, min(len(top), 3) + 1))
    lines.append(f"\n💬 Reply {digits} for full details & how to apply — right here in chat.")

    lines.append(f"\nTokens remaining: *{credits_remaining}*")
    if credits_remaining <= 1 and not free_run:
        # Peak-engagement nudge: they just saw real matches and are about to
        # run out of runs. The picker makes topping up a two-tap flow.
        lines.append("_Running low — type *buy tokens* to top up in seconds._")

    # The growth loop, at the one moment the product has just proved itself.
    lines.append("\n" + _referral_invite_line(phone_number))

    await _send_whatsapp(phone_number, "\n".join(lines))

    # Magic link to the match session page — as a tappable button, not a raw URL.
    link = _make_magic_link(phone_number, db, redirect_to=f"/matches/{match_session.id}")
    await _send_whatsapp_cta_url(
        phone_number,
        body="View all matches & draft applications on the web:",
        button_text="View all matches",
        url_link=link,
        footer=_link_expiry_note().strip("_"),
    )

    # 👍/👎 quality pulse once they've had time to browse the results — the
    # only signal that makes match quality measurable. Best-effort: lost on
    # redeploy, and skipped if a newer run supersedes this one.
    asyncio.create_task(_send_match_quality_pulse(phone_number, match_session.id))


async def _send_match_quality_pulse(phone: str, session_id: int) -> None:
    try:
        await asyncio.sleep(settings.MATCH_FEEDBACK_DELAY_SECONDS)
        db = SessionLocal()
        try:
            ws = db.query(WhatsAppSession).filter(WhatsAppSession.phone_number == phone).first()
            if ws is None or ws.last_match_session_id != session_id:
                return  # a fresh run replaced this one — its own pulse will fire
        finally:
            db.close()
        await _send_whatsapp_buttons(
            phone,
            "Quick pulse check — how did those matches look? Your 👍/👎 tunes your next run.",
            [("btn_match_good", "👍 On target"), ("btn_match_bad", "👎 Off target")],
        )
        record_server_event(phone, "match_feedback_prompt", str(session_id))
    except Exception as exc:
        log.warning("Match quality pulse failed | phone=%s | %s", phone[:6] + "****", exc)


async def _run_match_command_background(
    phone_number: str,
    graph_phone_number_id: str = "",
    match_scope: str = _MATCH_SCOPE_ALL,
) -> None:
    """Run matching in a detached task with its own DB session/context."""
    ctx_token = _wa_graph_phone_id.set(graph_phone_number_id) if graph_phone_number_id else None
    db = SessionLocal()
    try:
        await _handle_match_command(phone_number, db, match_scope=match_scope)
    except Exception as exc:
        log.exception("WhatsApp background match error | phone=%s | %s", phone_number[:6] + "****", exc)
    finally:
        db.close()
        _finish_match_run(phone_number)
        if ctx_token is not None:
            _wa_graph_phone_id.reset(ctx_token)


# ── Free first match run (durable) ───────────────────────────────────────────
# The run promised at the end of onboarding used to live only in the asyncio
# task that was about to perform it, so a deploy in that window silently broke
# the promise. `whatsapp_sessions.pending_first_match` is the durable record:
# set before the task starts, cleared when it finishes, resumed on the user's
# next message if the process died in between.

def _set_pending_first_match(phone: str, value: bool) -> None:
    """Best-effort flag write on its own session (callers are detached tasks)."""
    db = SessionLocal()
    try:
        ws = db.query(WhatsAppSession).filter(WhatsAppSession.phone_number == phone).first()
        if ws is not None and bool(ws.pending_first_match) != value:
            ws.pending_first_match = value
            db.commit()
    except Exception as exc:
        db.rollback()
        log.warning("pending_first_match write failed | phone=%s | %s", phone[:6] + "****", exc)
    finally:
        db.close()


async def _first_match_task(phone: str, graph_phone_number_id: str = "", delay_seconds: float = 3.0) -> None:
    """The free post-onboarding run, plus the enrichment nudge that follows it."""
    try:
        if delay_seconds:
            # Small delay so the welcome message lands before match updates.
            await asyncio.sleep(delay_seconds)
        # Freshness first: the automatic run scans the last WA_MATCH_RECENT_DAYS
        # and widens itself when that is too thin.
        await _run_match_command_background(phone, graph_phone_number_id, _MATCH_SCOPE_RECENT)
        # Results are on screen — best moment to ask for the one optional field
        # that sharpens matching most (certs left out of the 4-question
        # onboarding on purpose).
        await _send_post_match_enrichment(phone)
    finally:
        _set_pending_first_match(phone, False)


async def _resume_pending_first_match(wa_session: WhatsAppSession, db: Session) -> bool:
    """Kick off a first run this process never delivered. True when resumed."""
    if not getattr(wa_session, "pending_first_match", False):
        return False
    phone = wa_session.phone_number
    if not _try_start_match_run(phone):
        return False  # still running here — its own task will clear the flag
    record_server_event(phone, "first_match_resumed", "whatsapp")
    log.info("Resuming promised first match run | phone=%s", phone[:6] + "****")
    asyncio.create_task(_first_match_task(phone, _wa_graph_phone_id.get() or "", delay_seconds=0))
    return True


async def _send_post_match_enrichment(phone: str, db: Session | None = None) -> None:
    """Post-first-match profile enrichment nudge — certifications only.

    Sent once the auto first-match results have landed, and only when the
    profile has no certifications yet (they were dropped from required
    onboarding to keep signup at 4 questions). Chat mode has no NLU path for
    free-text profile edits, so the nudge routes through the existing *edit
    profile* magic-link flow rather than pretending to parse cert replies.
    Best-effort — never raises into the caller.
    """
    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        profile = db.query(CrewProfile).filter(CrewProfile.user_key == phone).first()
        if profile is None or (profile.certifications or "").strip():
            return
        await _send_whatsapp(
            phone,
            "🏅 Want sharper matches? Add your *certifications* (like STCW or ENG1) "
            "to your profile — type *edit profile* and I'll send you a secure link. "
            "Takes about 30 seconds.",
        )
    except Exception as exc:
        log.warning("Post-match enrichment nudge failed | phone=%s | %s", phone[:6] + "****", exc)
    finally:
        if own_db:
            db.close()



# ── In-chat match details ─────────────────────────────────────────────────────
# After a match run, the user can reply "1"/"2"/"3" for full job details or
# "draft 1" for an application email — without leaving WhatsApp. The web link
# stays available, but the chat must deliver the full payoff on its own.

def _nth_match_result(db: Session, wa_session: WhatsAppSession, n: int):
    """Return (result, job, total) for the nth result of the user's last run."""
    sid = wa_session.last_match_session_id
    if not sid:
        return None, None, 0
    results = (
        db.query(MatchSessionResult)
        .filter(MatchSessionResult.session_id == sid, MatchSessionResult.matched.is_(True))
        .order_by(MatchSessionResult.id.asc())  # insertion order == summary numbering
        .limit(9)
        .all()
    )
    if n > len(results):
        return None, None, len(results)
    result = results[n - 1]
    job = db.query(Job).filter(Job.id == result.job_id).first()
    return result, job, len(results)


def _job_apply_line(job: Job) -> str:
    if job.contact_email:
        return f"📧 *Apply to:* {job.contact_email}"
    if job.application_url:
        return f"🔗 *Apply here:* {job.application_url}"
    return "ℹ️ No direct contact on the listing — use the website link below to apply."


_FACTOR_LABELS = {
    "role": "Role", "location": "Location", "pay": "Pay", "contract": "Contract",
    "skills": "Skills", "certifications": "Certs", "experience": "Experience",
}


def _match_drivers_line(factor_scores_json: str | None) -> str:
    """Compact 'why this match' line from the top 3 factor scores, or ''.

    The engine also stores diagnostic ``det_*`` keys — those are internal and
    never shown to the user.
    """
    try:
        scores = json.loads(factor_scores_json or "{}")
    except ValueError:
        return ""
    if not isinstance(scores, dict):
        return ""
    ranked = sorted(
        (
            (k, v) for k, v in scores.items()
            if isinstance(v, (int, float)) and not str(k).startswith("det_")
        ),
        key=lambda kv: kv[1],
        reverse=True,
    )[:3]
    if not ranked:
        return ""
    return "📊 *Match drivers:* " + " · ".join(
        f"{_FACTOR_LABELS.get(k, str(k).title())} {int(v)}" for k, v in ranked
    )


async def _send_match_detail(phone: str, db: Session, wa_session: WhatsAppSession, n: int) -> None:
    result, job, total = _nth_match_result(db, wa_session, n)
    if total == 0:
        await _send_whatsapp(phone, "No match run on record yet — type *match* to find jobs for your profile.")
        return
    if result is None or job is None:
        await _send_whatsapp(phone, f"Your last run had *{total}* match{'es' if total != 1 else ''} — reply a number from 1 to {total}.")
        return

    lines = [f"⚓ *{job.title}*"]
    facts = []
    if job.yacht and job.yacht.lower() not in ("unknown", "n/a"):
        facts.append(f"🛥️ {job.yacht}" + (f" ({job.yacht_length_m}m)" if job.yacht_length_m else ""))
    if job.location:
        facts.append(f"📍 {job.location}")
    if job.salary_min or job.salary_max:
        cur = job.salary_currency or "EUR"
        if job.salary_min and job.salary_max:
            facts.append(f"💰 {cur} {job.salary_min:g}–{job.salary_max:g}/mo")
        else:
            facts.append(f"💰 {cur} {(job.salary_min or job.salary_max):g}/mo")
    if job.contract_type:
        facts.append(f"📋 {job.contract_type}")
    if job.start_date:
        facts.append(f"🗓️ Starts {job.start_date}")
    lines.append("\n".join(facts))
    # MatchSessionResult has no tier column, so derive it from the stored score
    # with the engine's own thresholds — same word the summary used.
    tier = _tier_label("", result.compatibility)
    tier_bit = f" · {tier} fit" if tier and tier != "a stretch" else (f" · {tier}" if tier else "")
    lines.append(f"\n*Match: {int(result.compatibility)}%{tier_bit}* — {result.reason or 'good overall fit.'}")

    try:
        strengths = json.loads(result.strengths or "[]")
    except ValueError:
        strengths = []
    if strengths:
        lines.append("✅ *Your edge:* " + "; ".join(str(s) for s in strengths[:3]))
    try:
        gaps = json.loads(result.gaps or "[]")
    except ValueError:
        gaps = []
    if gaps:
        lines.append("⚠️ *Mind the gap:* " + "; ".join(str(g) for g in gaps[:2]))

    drivers = _match_drivers_line(result.factor_scores)
    if drivers:
        lines.append(drivers)

    if job.description:
        lines.append(f"\n{job.description[:350]}{'…' if len(job.description) > 350 else ''}")

    lines.append(f"\n{_job_apply_line(job)}")
    lines.append(f"\n✍️ Reply *draft {n}* and I'll write your application email right here.")

    await _send_whatsapp(phone, "\n".join(lines))
    record_server_event(phone, "match_detail_viewed", str(job.id))
    await _send_whatsapp_buttons(
        phone,
        "Keep this one on your radar?",
        [
            (f"btn_save_{n}", "💾 Save"),
            (f"btn_dismiss_{n}", "🚫 Not for me"),
            (f"btn_draft_{n}", "✍️ Draft apply"),
        ],
    )


async def _send_application_draft(phone: str, db: Session, wa_session: WhatsAppSession, n: int) -> None:
    result, job, total = _nth_match_result(db, wa_session, n)
    if total == 0:
        await _send_whatsapp(phone, "No match run on record yet — type *match* to find jobs first.")
        return
    if result is None or job is None:
        await _send_whatsapp(phone, f"Your last run had *{total}* match{'es' if total != 1 else ''} — reply *draft 1* to *draft {total}*.")
        return
    if not settings.OPENAI_API_KEY:
        await _send_whatsapp(phone, "⚠️ AI drafting is temporarily unavailable. Try again soon.")
        return

    profile = db.query(CrewProfile).filter(CrewProfile.user_key == phone).first()
    if not profile:
        await _send_whatsapp(phone, "Set up your crew profile first — type *edit profile*.")
        return

    await _send_whatsapp(phone, f"✍️ Drafting your application for *{job.title}* — one moment…")

    from app.routes.crew_match import (
        _get_document_summary,
        _profile_summary,
        build_draft_email_system_prompt,
    )

    job_history_entries = (
        db.query(JobHistoryEntry)
        .filter(JobHistoryEntry.user_key == phone)
        .order_by(JobHistoryEntry.start_date.desc())
        .limit(5)
        .all()
    )
    doc_summary = _get_document_summary(db, phone)
    profile_text = _profile_summary(profile, job_history_entries, document_summary=doc_summary)
    profile_url = f"{settings.FRONTEND_BASE_URL}/crew/{profile.profile_slug}" if profile.profile_slug else ""
    system = build_draft_email_system_prompt(profile_text, profile.first_name or "the applicant", job, profile_url)

    try:
        parsed = await _call_openai(system, [], "Write the email.", model=settings.EMAIL_AI_MODEL)
    except Exception as exc:
        log.exception("Draft-email LLM call failed | phone=%s | %s", phone[:6] + "****", exc)
        parsed = {}
    body = str(parsed.get("body", "")).strip()
    if not body:
        await _send_whatsapp(phone, "⚠️ Drafting hit a snag — try *draft " + str(n) + "* again in a moment.")
        return
    subject = str(parsed.get("subject", "")).strip() or f"Application — {job.title}"

    msg = f"📨 *Your application draft*\n\n*Subject:* {subject}\n\n{body}"
    if job.contact_email:
        msg += f"\n\n📧 Copy it into an email to *{job.contact_email}* — good luck! 🍀"
    elif job.application_url:
        msg += f"\n\n🔗 Apply with it here: {job.application_url}"
    await _send_whatsapp(phone, msg)

    metrics.increment("whatsapp_apply_drafts")
    record_server_event(phone, "apply_draft", str(job.id))
    try:
        from app.models import JobDraftEvent
        existing = (
            db.query(JobDraftEvent)
            .filter(JobDraftEvent.job_id == job.id, JobDraftEvent.user_key == phone)
            .first()
        )
        if existing is None:
            db.add(JobDraftEvent(job_id=job.id, user_key=phone))
            db.commit()
    except Exception:
        db.rollback()


async def _handle_save_match(phone: str, db: Session, wa_session: WhatsAppSession, n: int) -> None:
    """💾 Save — keep match N from the last run on the user's saved list."""
    result, job, total = _nth_match_result(db, wa_session, n)
    if total == 0:
        await _send_whatsapp(phone, "No match run on record yet — type *match* to find jobs first.")
        return
    if result is None or job is None:
        await _send_whatsapp(phone, f"Your last run had *{total}* match{'es' if total != 1 else ''} — reply *save 1* to *save {total}*.")
        return
    _record_match_interaction(db, phone, job.id, "saved")
    record_server_event(phone, "match_saved", str(job.id))
    await _send_whatsapp(phone, f"💾 Saved *{job.title}* — type *saved* anytime to see your list.")


async def _handle_applied_match(phone: str, db: Session, wa_session: WhatsAppSession, n: int) -> None:
    """✅ Applied — log the application on match N; the hire-attribution hook."""
    result, job, total = _nth_match_result(db, wa_session, n)
    if total == 0:
        await _send_whatsapp(phone, "No match run on record yet — type *match* to find jobs first.")
        return
    if result is None or job is None:
        await _send_whatsapp(phone, f"Your last run had *{total}* match{'es' if total != 1 else ''} — reply *applied 1* to *applied {total}*.")
        return
    _record_match_interaction(db, phone, job.id, "applied")
    record_server_event(phone, "match_applied", str(job.id))
    await _send_whatsapp(
        phone,
        f"🤞 Logged — application in for *{job.title}*. Rooting for you!\n\n"
        "Keep me posted on how it goes. Spotted another fit? *draft N* writes the email for you.",
    )


async def _handle_dismiss_match(phone: str, db: Session, wa_session: WhatsAppSession, n: int) -> None:
    """🚫 Not for me — record the dismissal and roll straight to the next match."""
    result, job, total = _nth_match_result(db, wa_session, n)
    if total == 0:
        await _send_whatsapp(phone, "No match run on record yet — type *match* to find jobs first.")
        return
    if result is None or job is None:
        await _send_whatsapp(phone, f"Your last run had *{total}* match{'es' if total != 1 else ''} — reply *dismiss 1* to *dismiss {total}*.")
        return
    _record_match_interaction(db, phone, job.id, "dismissed")
    record_server_event(phone, "match_dismissed", str(job.id))
    if n < total:
        await _send_whatsapp(
            phone,
            f"🚫 Noted — I'll leave *{job.title}* out of future runs. Here's your next match:",
        )
        await _send_match_detail(phone, db, wa_session, n + 1)
    else:
        await _send_whatsapp(
            phone,
            f"🚫 Noted — I'll leave *{job.title}* out of future runs. "
            "That was the last match from this run — type *match* to scan for more.",
        )


# ── Saved jobs list ───────────────────────────────────────────────────────────
# The *saved* command lists saved jobs and stashes their ids in the session's
# partial_profile (same trick as the _retry* onboarding keys) so a bare digit
# reply drills into the saved list instead of the last match run. A fresh match
# run clears the stash, pointing digits back at the new results.

_SAVED_LIST_KEY = "_savedJobIds"


def _saved_list_context(wa_session: WhatsAppSession) -> list[int]:
    try:
        partial = json.loads(wa_session.partial_profile or "{}")
    except ValueError:
        return []
    ids = partial.get(_SAVED_LIST_KEY)
    return [int(i) for i in ids] if isinstance(ids, list) else []


def _set_saved_list_context(wa_session: WhatsAppSession, db: Session, job_ids: list[int]) -> None:
    try:
        partial = json.loads(wa_session.partial_profile or "{}")
    except ValueError:
        partial = {}
    partial[_SAVED_LIST_KEY] = job_ids
    wa_session.partial_profile = json.dumps(partial)
    db.commit()


def _clear_saved_list_context(wa_session: WhatsAppSession) -> None:
    """Drop the saved-list digit context (caller commits)."""
    try:
        partial = json.loads(wa_session.partial_profile or "{}")
    except ValueError:
        return
    if partial.pop(_SAVED_LIST_KEY, None) is not None:
        wa_session.partial_profile = json.dumps(partial)


async def _send_saved_jobs(phone: str, db: Session, wa_session: WhatsAppSession) -> None:
    """List up to 10 saved jobs, newest first, numbered for digit drill-down."""
    rows = (
        db.query(MatchInteraction)
        .filter(MatchInteraction.user_key == phone, MatchInteraction.action == "saved")
        .order_by(MatchInteraction.created_at.desc(), MatchInteraction.id.desc())
        .limit(10)
        .all()
    )
    if not rows:
        _clear_saved_list_context(wa_session)
        db.commit()
        await _send_whatsapp(
            phone,
            "💾 *My Jobs*\n\nNothing saved yet — after a *match* run, tap *Save* on any match to keep it here.",
        )
        return

    job_ids = [r.job_id for r in rows]
    jobs_by_id = {
        j.id: j for j in db.query(Job).filter(Job.id.in_(job_ids)).all()
    }
    lines = ["💾 *My Jobs*\n"]
    listed_ids: list[int] = []
    for jid in job_ids:
        job = jobs_by_id.get(jid)
        if not job:
            continue  # job pruned from the board since it was saved
        listed_ids.append(jid)
        lines.append(f"{len(listed_ids)}. *{job.title}* — {job.location}")
    if not listed_ids:
        _clear_saved_list_context(wa_session)
        db.commit()
        await _send_whatsapp(
            phone,
            "💾 *My Jobs*\n\nYour saved jobs are no longer on the board — type *match* to find fresh ones.",
        )
        return

    _set_saved_list_context(wa_session, db, listed_ids)
    lines.append(f"\n💬 Reply *1*–*{len(listed_ids)}* for full details & how to apply.")
    await _send_whatsapp(phone, "\n".join(lines))


async def _send_saved_job_detail(phone: str, db: Session, wa_session: WhatsAppSession, saved_ids: list[int], n: int) -> None:
    """Full details for the nth job on the saved list, straight from the Job row."""
    if n > len(saved_ids):
        await _send_whatsapp(
            phone,
            f"Your saved list has *{len(saved_ids)}* job{'s' if len(saved_ids) != 1 else ''} — reply a number from 1 to {len(saved_ids)}.",
        )
        return
    job = db.query(Job).filter(Job.id == saved_ids[n - 1]).first()
    if job is None:
        await _send_whatsapp(phone, "That job is no longer on the board — type *saved* to refresh your list.")
        return

    lines = [f"⚓ *{job.title}*"]
    facts = []
    if job.yacht and job.yacht.lower() not in ("unknown", "n/a"):
        facts.append(f"🛥️ {job.yacht}" + (f" ({job.yacht_length_m}m)" if job.yacht_length_m else ""))
    if job.location:
        facts.append(f"📍 {job.location}")
    if job.salary_min or job.salary_max:
        cur = job.salary_currency or "EUR"
        if job.salary_min and job.salary_max:
            facts.append(f"💰 {cur} {job.salary_min:g}–{job.salary_max:g}/mo")
        else:
            facts.append(f"💰 {cur} {(job.salary_min or job.salary_max):g}/mo")
    if job.contract_type:
        facts.append(f"📋 {job.contract_type}")
    if job.start_date:
        facts.append(f"🗓️ Starts {job.start_date}")
    lines.append("\n".join(facts))

    if job.description:
        lines.append(f"\n{job.description[:350]}{'…' if len(job.description) > 350 else ''}")

    lines.append(f"\n{_job_apply_line(job)}")
    lines.append("\n_Type *saved* for your list, or *match* to scan for fresh roles._")
    await _send_whatsapp(phone, "\n".join(lines))
    record_server_event(phone, "saved_job_viewed", str(job.id))


# ── Onboarding flow ───────────────────────────────────────────────────────────

# Inverted onboarding: value before profile.
#
# The 22 Sep transcript review found 15 of 20 stalled users sent exactly ONE
# message and never replied, and that a user who *did* finish needed ~5 messages
# and ~90 seconds before seeing a single job title. So the first message a
# brand-new user ever sees is fixed, LLM-free and deterministic — auditable,
# A/B-able, identical for everyone, no round-trip latency, and free of any
# token/pricing talk. It asks for ONE word, because one word is all we need to
# put real jobs on their screen on message two.
_FIRST_MESSAGE = (
    "I scan every live superyacht job and tell you which ones fit you. "
    "One word to start — what role are you after? "
    "(e.g. Deckhand, Stewardess, Engineer, Chef)"
)
# Back-compat alias — the old name is referenced by tests and win-back copy.
_FALLBACK_GREETING = _FIRST_MESSAGE

# Deterministic question order. Role comes first (it is the first message), then
# the three fields the matching engine still needs. The *sequence* is code, not
# an LLM decision; the LLM is only kept for extracting answers (and capturing
# volunteered extras) once the role preview has landed.
_ONBOARD_QUESTION_ORDER = ["desiredRole", "firstName", "currentLocation", "yearsExperience"]

# Short, one-at-a-time replacements for the chatty _FIELD_QUESTIONS copy.
_ONBOARD_QUESTIONS: dict[str, str] = {
    "desiredRole": "What role are you after? (e.g. Deckhand, Stewardess, Engineer, Chef)",
    "firstName": "What's your first name?",
    "currentLocation": "Where are you based right now? City or country is fine.",
    "yearsExperience": "How many years have you worked on boats? A rough number works.",
}

# Widen the role preview to a month when the last WA_MATCH_RECENT_DAYS are empty.
_ONBOARD_PREVIEW_FALLBACK_DAYS = 30
# Below this many recent jobs, a match run widens to all open jobs by itself.
_MATCH_MIN_RECENT_RESULTS = 3

_ONBOARD_NO_JOBS = (
    "Nothing live for that role this week — I'll ping you the moment one lands."
)

# The two buttons under the role preview. Routed by button *id*, but the plain
# text is accepted too so typing works as well as tapping.
_ONBOARD_RANK_CMDS: frozenset[str] = frozenset({
    "rank them for me", "rank them", "rank", "rank all", "rank me",
})
_ONBOARD_LIST_CMDS: frozenset[str] = frozenset({
    "just show the list", "just show me the list", "show me the list",
    "show the list", "just the list", "the list",
})


def _missing_onboard_fields(partial: dict) -> list[str]:
    """Required fields still unanswered, in deterministic question order."""
    return [f for f in _ONBOARD_QUESTION_ORDER if not str(partial.get(f, "")).strip()]


def _onboard_question(field: str) -> str:
    return _ONBOARD_QUESTIONS.get(field) or _FIELD_QUESTIONS.get(
        field, f"Could you tell me your {_FIELD_LABELS.get(field, field)}?"
    )


def _extract_role(text: str) -> str:
    """Pull a role out of a one-word-ish answer. '' when it isn't one.

    Deliberately deterministic and LLM-free: this answer gates the job preview,
    so it must be instant. Anything long or wordy falls through to a re-ask.
    """
    raw = (text or "").strip().strip(".,!?;:")
    if not raw or len(raw) > 60 or not re.search(r"[A-Za-z]", raw):
        return ""
    raw = re.sub(
        r"^(i'?m\s+an?|im\s+an?|i\s+am\s+an?|looking\s+for(\s+an?)?|a|an|the)\s+",
        "", raw, flags=re.IGNORECASE,
    ).strip()
    if not raw or len(raw.split()) > 4:
        return ""
    return raw.title()


def _posted_age(created_at: datetime | None) -> str:
    """'today' / 'yesterday' / '5d ago' — '' when the timestamp is missing."""
    if not created_at:
        return ""
    dt = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - dt).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days}d ago"


def _job_preview_line(job: Job) -> str:
    """'Deckhand · Antibes · 45m MY' — whatever of that the row actually has."""
    bits: list[str] = [str(job.role or job.title or "").strip()]
    if job.location:
        bits.append(str(job.location).strip())
    vessel = ""
    if job.yacht_length_m:
        vessel = f"{job.yacht_length_m:g}m"
    if job.yacht_type and len(str(job.yacht_type)) <= 12:
        vessel = f"{vessel} {job.yacht_type}".strip()
    if vessel:
        bits.append(vessel)
    return " · ".join(b for b in bits if b)


def _role_preview_jobs(db: Session, role: str) -> tuple[list[Job], int, bool]:
    """Cheap, deterministic role match over live jobs. (jobs, days, widened).

    Reuses the same zero-LLM substring/taxonomy matcher the paywall teaser uses,
    scoped to the last WA_MATCH_RECENT_DAYS. An empty week honestly falls back
    to the last month rather than pretending the board is dead.
    """
    from app.services.job_alerts import _matching_jobs

    def _window(days: int) -> list[Job]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        rows = (
            db.query(Job)
            .filter(Job.status.in_(["open", "priority"]), Job.created_at >= cutoff)
            .order_by(Job.created_at.desc())
            .all()
        )
        return _matching_jobs(rows, role)

    recent_days = max(1, settings.WA_MATCH_RECENT_DAYS)
    jobs = _window(recent_days)
    if jobs:
        return jobs, recent_days, False
    wide = _window(_ONBOARD_PREVIEW_FALLBACK_DAYS)
    return wide, _ONBOARD_PREVIEW_FALLBACK_DAYS, bool(wide)


async def _send_role_job_preview(
    phone: str, db: Session, role: str, partial: dict
) -> tuple[bool, str]:
    """Real job titles on message two. (preview_sent, text_for_history)."""
    jobs, _days, widened = _role_preview_jobs(db, role)
    record_server_event(phone, "onboard_role_jobs_shown", str(len(jobs)))
    if not jobs:
        return False, _ONBOARD_NO_JOBS

    n = len(jobs)
    plural = "s" if n != 1 else ""
    if widened:
        head = (
            f"Nothing new this week for *{role}* — but *{n}* job{plural} "
            f"landed in the last month."
        )
    else:
        head = f"Good — *{n}* live {role} job{plural} this week."

    shown = jobs[:3]
    head += " Freshest three:" if len(shown) == 3 else (" Here it is:" if len(shown) == 1 else " Freshest:")
    lines = [head]
    lines += ["• " + _job_preview_line(j) for j in shown]

    remaining = len([f for f in _missing_onboard_fields(partial) if f != "desiredRole"])
    target = f"all {n}" if n > 1 else "it"
    # Only call the run free when this user can actually pay for one — the
    # same lie in the win-back copy sent a user with 0 tokens straight to the
    # paywall from a button that said "free".
    free_bit = (
        " and your first run is free"
        if crew_match_free() or get_credit_balance(db, phone) >= 1 else ""
    )
    lines.append(
        f"\nWant me to rank {target} against your profile? "
        f"{remaining} quick question{'s' if remaining != 1 else ''}{free_bit}."
    )

    text = "\n".join(lines)
    await _send_whatsapp(phone, text)
    await _send_whatsapp_buttons(
        phone,
        "How do you want them?",
        [
            ("btn_onb_rank", "Rank them for me"),
            ("btn_onb_list", "Just show the list"),
        ],
    )
    return True, text


async def _send_role_job_list(phone: str, db: Session, role: str) -> int:
    """"Just show me the list" — top 10, title / location / posted age."""
    jobs, _days, _widened = _role_preview_jobs(db, role)
    if not jobs:
        await _send_whatsapp(phone, _ONBOARD_NO_JOBS)
        return 0

    n = len(jobs)
    lines = [f"*{n} live {role} job{'s' if n != 1 else ''}* — newest first:\n"]
    for i, job in enumerate(jobs[:10], 1):
        tail = [str(job.location).strip()] if job.location else []
        age = _posted_age(job.created_at)
        if age:
            tail.append(age)
        suffix = " — " + " · ".join(tail) if tail else ""
        lines.append(f"{i}. *{job.title or job.role or role}*{suffix}")
    if n > 10:
        lines.append(f"\n_…and {n - 10} more._")
    await _send_whatsapp(phone, "\n".join(lines))
    return n


def _onboard_retry_prompt(partial: dict, field: str) -> str:
    """Re-ask `field`, escalating to a dead-straight prompt after two misses.

    Keeps the user off the "didn't quite catch that" treadmill that the review
    found people abandoning.
    """
    question = _onboard_question(field)
    if partial.get("_retryField") == field:
        partial["_retryCount"] = int(partial.get("_retryCount", 0)) + 1
    else:
        partial["_retryField"] = field
        partial["_retryCount"] = 1
    if int(partial["_retryCount"]) >= 2:
        return (
            f"Let's keep it simple 👍 {question}\n\n"
            "_Just reply with the answer on its own — nothing else needed._"
        )
    return f"Hmm, didn't quite catch that — no worries! {question}"


async def _run_onboarding(wa_session: WhatsAppSession, user_message: str, db: Session) -> str | None:
    """Inverted onboarding: value first, profile second.

    1. Fixed, LLM-free first message asking for one word (the role).
    2. The role answer immediately buys real job titles — count + freshest 3 —
       with a *Rank them for me* / *Just show the list* choice.
    3. Only then the remaining required fields, one deterministic question at a
       time (the LLM still extracts the answers and any volunteered extras).
    """
    history = json.loads(wa_session.history)
    partial = json.loads(wa_session.partial_profile)
    phone = wa_session.phone_number

    # ── 1. Brand-new user ────────────────────────────────────────────────────
    # No LLM call at all: deterministic, auditable, A/B-able, and instant.
    if not history:
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": _FIRST_MESSAGE})
        _save_session(wa_session, db, history, partial)
        return _FIRST_MESSAGE

    cmd = (user_message or "").strip().lower()
    role_so_far = str(partial.get("desiredRole", "")).strip()

    # ── 2. The role answer → real jobs on screen ─────────────────────────────
    if not role_so_far:
        role = _extract_role(user_message)
        if not role:
            message = _onboard_retry_prompt(partial, "desiredRole")
            history.append({"role": "user", "content": user_message})
            history.append({"role": "assistant", "content": message})
            _save_session(wa_session, db, history, partial)
            return message

        _before = dict(partial)
        partial["desiredRole"] = role
        _record_onboard_fields(phone, _before, partial)
        partial.pop("_retryField", None)
        partial.pop("_retryCount", None)
        history.append({"role": "user", "content": user_message})

        preview_sent, preview_text = await _send_role_job_preview(phone, db, role, partial)
        if preview_sent:
            # Buttons are on screen — wait for the tap rather than piling on
            # another question in the same breath.
            history.append({"role": "assistant", "content": preview_text})
            _save_session(wa_session, db, history, partial)
            return None

        # Honest about an empty board, but onboarding continues.
        message = preview_text + "\n\n" + _onboard_question(_missing_onboard_fields(partial)[0])
        history.append({"role": "assistant", "content": message})
        _save_session(wa_session, db, history, partial)
        return message

    # ── 3. Preview buttons ───────────────────────────────────────────────────
    if cmd in _ONBOARD_LIST_CMDS or cmd in _ONBOARD_RANK_CMDS:
        tapped_list = cmd in _ONBOARD_LIST_CMDS
        listed = 0
        if tapped_list:
            record_server_event(phone, "onboard_list_tapped", role_so_far)
            listed = await _send_role_job_list(phone, db, role_so_far)
        history.append({"role": "user", "content": user_message})

        missing = _missing_onboard_fields(partial)
        if missing:
            if tapped_list:
                lead = "Want them ranked, strongest fit first? " if listed else ""
            else:
                lead = "Good — "
            message = lead + _onboard_question(missing[0])
            history.append({"role": "assistant", "content": message})
            _save_session(wa_session, db, history, partial)
            return message

        # Nothing left to ask — finish the profile instead of looping.
        message = "That's a wrap — your crew profile is set. 🎉"
        history.append({"role": "assistant", "content": message})
        return await _finish_onboarding(wa_session, db, history, partial, message)

    # ── 4. Ordinary field answer ─────────────────────────────────────────────
    # The LLM still does extraction (and captures volunteered extras), but the
    # question sequence below is deterministic — never an LLM decision.
    system = _build_onboard_system(partial)
    try:
        parsed = await _call_openai(system, history, user_message)
    except Exception as exc:
        # Deterministic fallback extraction below keeps onboarding moving.
        log.exception("Onboarding LLM call failed | phone=%s | %s", phone[:6] + "****", exc)
        parsed = {}

    updates = parsed.get("updates") if isinstance(parsed.get("updates"), dict) else {}
    clean_updates = {
        k: str(v).strip() for k, v in updates.items()
        if isinstance(k, str) and v and str(v).strip()
    }
    if not parsed:
        clean_updates = _fallback_extract(partial, user_message)
        log.warning("LLM failed — fallback extraction | updates=%s", clean_updates)

    _before = dict(partial)
    partial = _apply_updates(partial, clean_updates)
    _record_onboard_fields(phone, _before, partial)
    if clean_updates:
        # Progress made — clear the consecutive-retry tracker for the stuck field.
        partial.pop("_retryField", None)
        partial.pop("_retryCount", None)

    missing = _missing_onboard_fields(partial)
    done = not missing
    if missing:
        question = _onboard_question(missing[0])
        if clean_updates:
            filled = len(_ONBOARD_QUESTION_ORDER) - len(missing)
            _acks = ["Got it.", "Noted.", "Thanks.", "Nice one."]
            ack = _acks[filled % len(_acks)]
            if len(missing) == 1:
                message = f"{ack} Last one — {question[0].lower() + question[1:]}"
            else:
                message = f"{ack} {question}"
        else:
            message = _onboard_retry_prompt(partial, missing[0])
    else:
        message = "That's a wrap — your crew profile is set. 🎉"

    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": message})

    if done:
        return await _finish_onboarding(wa_session, db, history, partial, message)

    _save_session(wa_session, db, history, partial)
    return message


async def _finish_onboarding(
    wa_session: WhatsAppSession,
    db: Session,
    history: list,
    partial: dict,
    message: str,
) -> None:
    """Profile complete: persist it, kick the free first run, send the welcome."""
    _save_profile_to_db(wa_session.phone_number, partial, db)
    _save_session(wa_session, db, history, partial, mode="chat")
    metrics.increment("onboard_completed")
    record_server_event(wa_session.phone_number, "onboard_completed")
    link = _make_magic_link(wa_session.phone_number, db)
    name = partial.get("firstName", "crew")

    # Growth loop: an invited user is only real once they finish onboarding,
    # so this is where both sides get paid — exactly once.
    referrer = _credit_referral(wa_session, db)

    # Activation moment: run the first match immediately on the free signup
    # token instead of hoping the user discovers the *match* command later.
    balance = get_credit_balance(db, wa_session.phone_number)
    first_match_started = (balance > 0 or crew_match_free()) and _try_start_match_run(wa_session.phone_number)
    if first_match_started:
        record_server_event(wa_session.phone_number, "first_match_auto_run", "whatsapp")
        graph_phone_number_id = _wa_graph_phone_id.get() or ""
        # The promise ("your results land right here") outlives this process,
        # so it is written down: a deploy between here and the run resumes it
        # on the user's next message instead of stranding them.
        wa_session.pending_first_match = True
        db.commit()
        asyncio.create_task(_first_match_task(wa_session.phone_number, graph_phone_number_id))

    message += (
        f"\n\n🎉 *Welcome to the fleet, {name}!* Your crew profile is live.\n\n"
    )
    if first_match_started:
        message += (
            "🚀 I'm already ranking the live jobs against your profile, on the house — "
            "your results land right here in a minute or two.\n\n"
        )
    if referrer:
        message += (
            f"🎁 You came in on a friend's invite — *+{_REFERRAL_BONUS_TOKENS} match runs* "
            "added to both your accounts.\n\n"
        )
    profile = db.query(CrewProfile).filter(CrewProfile.user_key == wa_session.phone_number).first()
    if profile is not None:
        message += (
            f"🔗 *Your public profile:* {_public_profile_url(db, profile)} — "
            "send it to any captain or recruiter.\n\n"
        )
    if crew_match_free():
        message += (
            "💳 *Find Matches* runs are free right now — run as many as you like. "
            "_Type *help* anytime to see what I can do for you._ ⚡"
        )
    else:
        message += (
            f"💳 *Tokens:* Each *Find Matches* run uses *1 token* — "
            f"type *buy tokens* to top up, or submit a valid job to earn a free token. "
            f"_Type *help* anytime to see what I can do for you._ ⚡"
        )
    await _send_whatsapp(wa_session.phone_number, message)
    if referrer:
        await _notify_referrer(referrer, db)
    await _send_whatsapp_cta_url(
        wa_session.phone_number,
        body="To really stand out, upload your docs — CV, passport, STCW & certs:",
        button_text="Upload docs",
        url_link=link,
        footer=_link_expiry_note().strip("_"),
    )
    return None


# ── Chat / interview flow ─────────────────────────────────────────────────────

async def _run_chat(wa_session: WhatsAppSession, user_message: str, db: Session) -> str | None:
    """Route a command. Returns a reply string, or None if the handler sent messages itself."""
    cmd = user_message.strip().lower()
    phone = wa_session.phone_number

    if cmd in ("help", "commands", "menu", "hi", "hey", "hello"):
        await _send_help_menu(phone, db)
        return None

    if cmd in ("credits", "balance", "my credits", "tokens", "my tokens"):
        bal = get_credit_balance(db, phone)
        await _send_whatsapp_buttons(
            phone,
            _credits_standalone_message(bal),
            [("cmd_subscribe", "Buy Tokens"), ("btn_submit_job", "Submit Job"), ("btn_menu", "Menu")],
        )
        return None
    if cmd in ("feedback", "give feedback", "review", "survey"):
        eligible, _setting = feedback_is_eligible(db, user_key=phone, source="whatsapp_message")
        if not eligible:
            await _send_whatsapp_buttons(
                phone,
                "💬 Feedback rewards are not open for your account right now.",
                [("btn_menu", "Menu")],
            )
            return None
        await _send_feedback_request(phone, db)
        return None

    if cmd in ("subscribe", "pro", "upgrade", "paid", "subscription", "buy tokens", "buy", "top up", "topup"):
        await _send_token_pack_picker(phone, db)
        return None

    if cmd.startswith("buy pack "):
        raw = cmd.removeprefix("buy pack ").strip()
        tokens = int(raw) if raw.isdigit() else 0
        await _start_whatsapp_checkout(phone, tokens, db)
        return None

    # "unsubscribe" deliberately absent — it is an opt-out keyword, handled
    # before routing (see _handle_opt_out_keywords), never a billing command.
    if cmd in ("cancel subscription", "cancel pro", "cancel"):
        bal = get_credit_balance(db, phone)
        w = "token" if bal == 1 else "tokens"
        await _send_whatsapp_buttons(
            phone,
            f"CARVER is pay-per-token — no recurring plan to cancel.\n\n"
            f"Your balance: *{bal} {w}*.",
            [("cmd_subscribe", "Buy Tokens"), ("btn_menu", "Menu")],
        )
        return None

    if cmd in ("refer", "invite", "referral", "refer a friend", "invite a friend", "my code"):
        record_server_event(phone, "referral_link_requested", "whatsapp")
        await _send_whatsapp(
            phone,
            f"🤝 *Your invite code: {_referral_code(phone)}*\n\n"
            + _referral_invite_line(phone)
            + "\n\nThey get a profile and their first ranked jobs in a couple of minutes — "
            f"and *{_REFERRAL_BONUS_TOKENS} runs* land on both accounts the moment they finish signing up.",
        )
        return None

    if cmd in ("profile link", "my link", "public profile", "share profile", "my profile link"):
        profile = db.query(CrewProfile).filter(CrewProfile.user_key == phone).first()
        if not profile:
            await _send_whatsapp(
                phone,
                "You don't have a crew profile yet — type *edit profile* to set one up, "
                "then I'll give you a public link to share.",
            )
            return None
        record_server_event(phone, "profile_link_shared", "whatsapp")
        await _send_whatsapp(
            phone,
            f"🔗 *Your public crew profile*\n{_public_profile_url(db, profile)}\n\n"
            "Send it to a captain, an agency or a group — no login needed to view it. "
            "A complete profile (docs, certs, photo) is what makes it land.",
        )
        return None

    if cmd in ("profile", "my profile", "show profile"):
        text = await _handle_profile_command(phone, db)
        await _send_whatsapp(phone, text)
        await _send_whatsapp_buttons(
            phone,
            "What's next?",
            [("btn_edit_profile", "Edit Profile"), ("btn_find_matches", "Matches (1 token)"), ("btn_menu", "Main Menu")],
        )
        return None

    if cmd in ("docs", "documents", "my docs"):
        text = await _handle_docs_command(phone, db)
        link = _make_magic_link(phone, db)
        await _send_whatsapp_cta_url(
            phone,
            body=text + "\n\n📎 *Upload or update your crew docs below.*",
            button_text="Upload docs",
            url_link=link,
            footer=_link_expiry_note().strip("_"),
        )
        await _send_whatsapp_buttons(
            phone,
            "Need anything else?",
            [("btn_view_profile", "View Profile"), ("btn_find_matches", "Matches (1 token)"), ("btn_menu", "Main Menu")],
        )
        return None

    if cmd in ("upload", "upload docs", "add docs", "add documents"):
        link = _make_magic_link(phone, db)
        await _send_whatsapp_cta_url(
            phone,
            header="Upload Crew Documents 📎",
            body="Tap below to upload your CV, passport, STCW, ENG1 & certs — vessels require these for crew.",
            button_text="Upload docs",
            url_link=link,
            footer=_link_expiry_note().strip("_"),
        )
        await _send_whatsapp_buttons(
            phone,
            "Anything else?",
            [("btn_view_profile", "View Profile"), ("btn_find_matches", "Matches (1 token)"), ("btn_menu", "Main Menu")],
        )
        return None

    if cmd in ("edit", "edit profile", "update", "update profile", "change profile"):
        link = _make_magic_link(phone, db)
        await _send_whatsapp_cta_url(
            phone,
            header="Edit Your Crew Profile ✏️",
            body="Tap below to update your profile — role, experience, certs, salary expectations & more.",
            button_text="Edit profile",
            url_link=link,
            footer=_link_expiry_note().strip("_"),
        )
        await _send_whatsapp_buttons(
            phone,
            "Anything else?",
            [("btn_view_profile", "View Profile"), ("btn_find_matches", "Matches (1 token)"), ("btn_menu", "Main Menu")],
        )
        return None

    if cmd in ("jobs", "open jobs", "positions", "vacancies"):
        await _handle_jobs_command(phone, db)
        return None

    # Bare digit → drill into the saved list when it was shown last, otherwise
    # into that result from the last match run, in chat.
    digit_match = re.fullmatch(r"[1-9]", cmd)
    if digit_match:
        saved_ids = _saved_list_context(wa_session)
        if saved_ids:
            await _send_saved_job_detail(phone, db, wa_session, saved_ids, int(cmd))
        else:
            await _send_match_detail(phone, db, wa_session, int(cmd))
        return None

    # "draft N" → ghost-write the application email for match N, in chat.
    draft_match = re.fullmatch(r"draft\s*([1-9])", cmd)
    if draft_match:
        await _send_application_draft(phone, db, wa_session, int(draft_match.group(1)))
        return None

    # "save N" / "dismiss N" → record engagement on match N from the last run.
    save_match = re.fullmatch(r"save\s*([1-9])", cmd)
    if save_match:
        await _handle_save_match(phone, db, wa_session, int(save_match.group(1)))
        return None
    dismiss_match = re.fullmatch(r"dismiss\s*([1-9])", cmd)
    if dismiss_match:
        await _handle_dismiss_match(phone, db, wa_session, int(dismiss_match.group(1)))
        return None

    # "applied N" → log an application on match N (hire-attribution signal).
    applied_match = re.fullmatch(r"applied\s*([1-9])", cmd)
    if applied_match:
        await _handle_applied_match(phone, db, wa_session, int(applied_match.group(1)))
        return None

    # 👍/👎 pulse replies — the run-level match-quality signal.
    if cmd in ("match feedback good", "match feedback bad"):
        verdict = "good" if cmd.endswith("good") else "bad"
        sid = wa_session.last_match_session_id or 0
        record_server_event(phone, "match_feedback", f"{verdict}:{sid}")
        if verdict == "good":
            await _send_whatsapp(
                phone,
                "Love it! 🎯 Reply *1*–*3* for full details, or *draft 1* and I'll write your application email right here.",
            )
        else:
            await _send_whatsapp_buttons(
                phone,
                "Thanks — honest feedback tunes your matches. 🔧 Most misses come from a thin profile: "
                "certs, preferred locations and salary sharpen the next run a lot.",
                [("btn_edit_profile", "Edit Profile"), ("btn_find_matches", "Run again"), ("btn_menu", "Menu")],
            )
        return None

    # Next-day "did you apply?" replies.
    if cmd in ("applied yes", "yes, applied", "i applied", "applied"):
        record_server_event(phone, "apply_followup_reply", "yes")
        await _send_whatsapp(
            phone,
            "Legend! 🙌 Which one? Reply *applied 1*, *applied 2*, … and I'll log it against the job.",
        )
        return None
    if cmd in ("applied not yet", "not yet"):
        record_server_event(phone, "apply_followup_reply", "not_yet")
        await _send_whatsapp(
            phone,
            "No stress — your matches aren't going anywhere. Reply *1*–*3* for details, "
            "or *draft 1* and I'll write the application email for you. ✍️",
        )
        return None
    if cmd in ("applied none", "none fit", "none fit me"):
        record_server_event(phone, "apply_followup_reply", "none_fit")
        await _send_whatsapp_buttons(
            phone,
            "Good to know — that helps me aim better. 🔧 A fuller profile (certs, preferred "
            "locations, salary) usually turns up stronger fits.",
            [("btn_edit_profile", "Edit Profile"), ("btn_find_matches", "Run again"), ("btn_menu", "Menu")],
        )
        return None

    if cmd in ("saved", "saved jobs", "my jobs", "my saved jobs"):
        await _send_saved_jobs(phone, db, wa_session)
        return None

    if cmd in ("match", "find jobs", "find matches", "matching", "find me jobs", "job match"):
        await _send_match_scope_menu(phone)
        return None

    match_scope: str | None = None
    if cmd in ("match recent", "recent matches", "find recent", "find recent matches", "recent jobs", "recent posts"):
        match_scope = _MATCH_SCOPE_RECENT
    elif cmd in ("match all", "all matches", "find all", "all jobs", "all db jobs", "database jobs"):
        match_scope = _MATCH_SCOPE_ALL

    if match_scope:
        if not _try_start_match_run(phone):
            await _send_whatsapp(
                phone,
                "⏳ A *Find Matches* run is already in progress. I'll send your results here as soon as it's done.",
            )
            return None
        graph_phone_number_id = _wa_graph_phone_id.get() or ""
        asyncio.create_task(_run_match_command_background(phone, graph_phone_number_id, match_scope))
        scope_text = "recent postings" if match_scope == _MATCH_SCOPE_RECENT else "all database jobs"
        await _send_whatsapp(phone, f"🚀 Starting your *Find Matches* run against *{scope_text}* — you'll get updates here shortly.")
        return None

    if cmd in ("submit job", "post job", "add job", "submit a job", "post a job"):
        wa_session.mode = "job_submit"
        db.commit()
        await _send_whatsapp(
            phone,
            "📸 *Submit a job to the board*\n\n"
            "Saw something in a crew *group*, *page*, or *post*? Share it easily:\n"
            "• Send *screenshot(s)* of the listing (several photos in a row are fine), or\n"
            "• *Paste* the job text here\n\n"
            "_I'll read it with AI and add it to the board if it's a real yacht crew role._",
        )
        return None

    # Unrecognised input → show the menu
    await _send_help_menu(phone, db)
    return None


# ── Delivery status callbacks ─────────────────────────────────────────────────
# Meta reports the life of an *outbound* message on a separate `statuses` array
# of the same webhook: sent → delivered → read, or a terminal failed/deleted.
# Without this a paid template blast is a black box — ten sends and no idea
# whether they landed, were read, or were refused.
#
# Retries re-deliver earlier rungs out of order, so a row only ever climbs the
# ladder. `failed` is the exception: it overwrites anything, because a message
# Meta reported as sent and then failed did not arrive.
_STATUS_RANK: dict[str, int] = {"sent": 1, "delivered": 2, "read": 3}
_TERMINAL_STATUSES: frozenset[str] = frozenset({"failed", "deleted"})

# Which statuses are worth a funnel event. `sent` is not one — we already know
# we sent it, that's why there's a row.
_STATUS_EVENTS: dict[str, str] = {
    "delivered": "wa_message_delivered",
    "read": "wa_message_read",
    "failed": "wa_message_failed",
}

# Three Meta codes, one meaning: this number will not be given our marketing
# templates. Spelled out in the log because nobody remembers the numbers.
_UNREACHABLE_ERROR_CODES: frozenset[str] = frozenset({"131049", "131026", "130472"})
_UNREACHABLE_NOTE = (
    "user cannot receive marketing templates — Meta is withholding them; "
    "re-sending this template to this number will keep failing"
)

# payload_json `source` tags written by the proactive loops. Conversational
# replies carry none, and their receipts would drown the funnel table.
_PROACTIVE_PAYLOAD_SOURCES: frozenset[str] = frozenset({
    "job_alerts", "apply_followup", "window_winback", "checkout_recovery",
    "agency_digest", "proactive",
})


def _status_error_summary(errors: list | None) -> tuple[str, str]:
    """Return (code, "code: title — details") for the first error on a status."""
    first = (errors or [{}])[0] or {}
    code = str(first.get("code") or "").strip()
    title = str(first.get("title") or "").strip()
    details = str((first.get("error_data") or {}).get("details") or "").strip()
    text = f"{code}: {title}".strip(": ") if (code or title) else ""
    if details:
        text = f"{text} — {details}" if text else details
    return code, text[:300]


def _status_timestamp(raw: object) -> datetime:
    """Meta sends Unix seconds as a string; fall back to now if it's junk."""
    try:
        return datetime.fromtimestamp(int(str(raw)), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return datetime.now(timezone.utc)


def _is_proactive_outbound(row: WhatsAppMessage) -> bool:
    """True for template sends and proactive-loop pushes — not for replies."""
    if (row.message_type or "") == "template":
        return True
    try:
        payload = json.loads(row.payload_json or "{}") or {}
    except (TypeError, ValueError):
        return False
    return str(payload.get("source") or "") in _PROACTIVE_PAYLOAD_SOURCES


def _apply_status_update(db: Session, item: dict) -> None:
    """Apply one Meta `statuses[]` entry to its whatsapp_messages row."""
    meta_id = str(item.get("id") or "").strip()
    new_status = str(item.get("status") or "").strip().lower()
    if not meta_id or not new_status:
        return

    row = db.query(WhatsAppMessage).filter(WhatsAppMessage.meta_message_id == meta_id).first()
    if row is None:
        # Sends that predate status recording, and messages sent from the Meta
        # console, both land here. Normal — not worth a warning.
        log.debug("WhatsApp status for unknown message | id=%s | status=%s", meta_id, new_status)
        return

    current = (row.status or "").strip().lower()
    if new_status == "failed":
        moved = current != "failed"
    elif current in _TERMINAL_STATUSES:
        moved = False
    elif new_status == "deleted":
        moved = True
    else:
        moved = _STATUS_RANK.get(new_status, 0) > _STATUS_RANK.get(current, 0)
    if not moved:
        # A retry of a rung we already have. Silently done — re-recording it
        # would double-count the funnel event.
        return

    code = ""
    row.status = new_status[:16]
    row.status_at = _status_timestamp(item.get("timestamp"))
    if new_status == "failed":
        code, row.status_error = _status_error_summary(item.get("errors"))
    db.commit()

    if new_status == "failed":
        phone = (row.phone_number or str(item.get("recipient_id") or "")).strip()
        log.warning(
            "WhatsApp outbound failed | phone=****%s | type=%s | code=%s | %s%s",
            phone[-4:] or "????",
            row.message_type or "unknown",
            code or "?",
            row.status_error or "no detail",
            f" | {_UNREACHABLE_NOTE}" if code in _UNREACHABLE_ERROR_CODES else "",
        )

    event = _STATUS_EVENTS.get(new_status)
    if event and (row.direction or "") == "outbound" and _is_proactive_outbound(row):
        record_server_event(row.phone_number, event, code or None)


def _process_status_callbacks(items: list[dict]) -> None:
    """Record a webhook's delivery receipts. Owns its DB session; never raises.

    Per-item isolation on purpose: one malformed status must not cost us the
    other nine receipts in the same callback.
    """
    db = SessionLocal()
    try:
        for item in items:
            try:
                _apply_status_update(db, item or {})
            except Exception as exc:
                db.rollback()
                log.warning(
                    "WhatsApp status callback failed | id=%s | %s",
                    (item or {}).get("id"), exc,
                )
    except Exception as exc:  # pragma: no cover — session setup only
        log.warning("WhatsApp status callback batch failed | %s", exc)
    finally:
        db.close()


def outbound_status_summary(db: Session, since: datetime) -> dict[str, int]:
    """Counts by delivery status for template sends since `since`.

    Answers the only question a paid reactivation sweep leaves open: of the N
    templates we bought, how many landed, how many were read, how many bounced.
    `pending` is the tail Meta has not reported on yet.
    """
    rows = (
        db.query(WhatsAppMessage.status, func.count(WhatsAppMessage.id))
        .filter(
            WhatsAppMessage.direction == "outbound",
            WhatsAppMessage.message_type == "template",
            WhatsAppMessage.created_at >= since,
        )
        .group_by(WhatsAppMessage.status)
        .all()
    )
    summary: dict[str, int] = {"sent": 0, "delivered": 0, "read": 0, "failed": 0, "pending": 0}
    for status_value, count in rows:
        key = (status_value or "").strip().lower() or "pending"
        summary[key] = summary.get(key, 0) + int(count or 0)
    summary["total"] = sum(summary.values())
    return summary


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/webhooks/whatsapp", response_class=PlainTextResponse)
async def whatsapp_verify(request: Request):
    """Meta webhook verification handshake."""
    params = request.query_params
    if params.get("hub.verify_token") == settings.META_VERIFY_TOKEN:
        log.info("WhatsApp webhook verified")
        return PlainTextResponse(params.get("hub.challenge", ""))
    log.warning("WhatsApp webhook verification failed — token mismatch")
    raise HTTPException(status_code=403, detail="Verification failed")


# Commands that should work regardless of session mode (onboarding, job_submit, etc.).
# This ensures tapping "Buy Tokens" or "Help" from the WhatsApp menu always works.
_GLOBAL_CMDS: frozenset[str] = frozenset({
    "subscribe", "pro", "upgrade", "paid", "subscription",
    "buy tokens", "buy", "top up", "topup",
    "cancel subscription", "cancel pro", "cancel",
    "help", "commands", "menu",
    "credits", "balance", "my credits", "tokens", "my tokens",
    "feedback", "give feedback", "review", "survey",
})

# Extra commands that work *during* onboarding, but only once the fixed first
# message has been sent. The gate matters: the website's wa.me CTAs prefill
# "match · <tag>", so a brand-new user's very first message is literally
# "match" — intercepting that would swallow the greeting. Everything here is
# read-only or a menu, so it never strands a half-finished profile; the next
# message resumes onboarding where it left off.
_ONBOARDING_ALLOWED_CMDS: frozenset[str] = frozenset({
    "jobs", "open jobs", "positions", "vacancies",
    "match", "find jobs", "find matches", "matching", "find me jobs", "job match",
    "hey", "hi", "hello",
})


async def _process_whatsapp_message(
    phone_number: str,
    user_text: str,
    graph_phone_number_id: str = "",
    meta_message_id: str = "",
    inbound_message_type: str = "text",
) -> None:
    """Handle a parsed WhatsApp message in the background (owns its own DB session)."""
    ctx_token = _wa_graph_phone_id.set(graph_phone_number_id) if graph_phone_number_id else None
    db = SessionLocal()
    try:
        # Blue ticks + "typing…" the moment processing starts, so the user
        # never stares at an unread message while the bot works.
        await _send_typing_indicator(meta_message_id)
        _record_whatsapp_message(
            phone_number,
            "inbound",
            inbound_message_type,
            user_text,
            meta_message_id=meta_message_id,
            graph_phone_number_id=graph_phone_number_id,
        )
        wa_session = _get_or_create_session(phone_number, db)
        # Groundwork for win-back sweeps: stamp every inbound touch.
        wa_session.last_active_at = datetime.now(timezone.utc)
        db.commit()

        # Strip the website's "· <tag>" acquisition marker before anything
        # else reads the message.
        if _is_first_contact(wa_session):
            user_text = _record_first_contact(phone_number, wa_session, user_text, db)

        # A first run we promised but never delivered (deploy mid-onboarding)
        # restarts here, alongside — never instead of — this message's reply.
        await _resume_pending_first_match(wa_session, db)

        # Opt-out beats command routing — see _handle_opt_out_keywords.
        if await _handle_opt_out_keywords(phone_number, wa_session, user_text, db):
            metrics.increment("whatsapp_messages")
            return

        _cmd = user_text.strip().lower()

        # Feedback invitation rides along AFTER the user's command is answered
        # (never instead of it), at most once per cooldown window.
        feedback_eligible, _feedback_setting = feedback_is_eligible(db, user_key=phone_number, source="whatsapp_message")
        invite_feedback = (
            feedback_eligible
            and not _feedback_already_submitted(db, phone_number)
            and _cmd not in ("feedback", "give feedback", "review", "survey")
            and _feedback_prompt_due(wa_session)
        )

        async def _finish() -> None:
            if invite_feedback:
                await _send_feedback_request(phone_number, db)
                wa_session.feedback_prompted_at = datetime.now(timezone.utc)
                db.commit()
            metrics.increment("whatsapp_messages")

        # Global commands bypass onboarding / job-submit modes so the user
        # can always buy tokens, check balance, or open the help menu.
        # `jobs` / `match` / `hey` additionally work mid-onboarding, but only
        # after the first message — see _ONBOARDING_ALLOWED_CMDS.
        _onboarding_cmd_ok = (
            wa_session.mode == "onboarding"
            and _cmd in _ONBOARDING_ALLOWED_CMDS
            and (getattr(wa_session, "history", None) or "[]") != "[]"
        )
        if (wa_session.mode != "chat" and _cmd in _GLOBAL_CMDS) or _onboarding_cmd_ok:
            reply = await _run_chat(wa_session, user_text, db)
            if reply is not None:
                await _send_whatsapp(phone_number, reply)
            await _finish()
            return

        if wa_session.mode == "job_submit":
            # Keep mode until we're done so concurrent image webhooks still see job_submit
            # (otherwise a second photo triggers the crew document upload flow).
            try:
                if not settings.OPENAI_API_KEY:
                    await _send_whatsapp(phone_number, "⚠️ AI processing is temporarily unavailable. Try again soon.")
                else:
                    await _send_job_review_wait(phone_number, "text")
                    # The ack cleared the typing bubble — bring it back for the
                    # slow AI review that follows.
                    await _send_typing_indicator(meta_message_id)
                    await _process_job_text_submission(phone_number, user_text, db)
                await _send_whatsapp_buttons(
                    phone_number,
                    "What's next?\n\n_Reply *balance* anytime._",
                    [("btn_submit_job", "Submit Another"), ("btn_find_matches", "Matches (1 token)"), ("btn_menu", "Menu")],
                )
            finally:
                wa_session.mode = "chat"
                db.commit()
            await _finish()
            return

        if wa_session.mode == "onboarding":
            reply = await _run_onboarding(wa_session, user_text, db)
        else:
            reply = await _run_chat(wa_session, user_text, db)
        if reply is not None:
            await _send_whatsapp(phone_number, reply)
        await _finish()
    except Exception as exc:
        log.exception("WhatsApp message processing error | phone=%s | %s", phone_number[:6] + "****", exc)
        # Anything that got here (most often a failed LLM call) would otherwise
        # leave the user's message unanswered. Say something.
        try:
            await _send_whatsapp(phone_number, _GLITCH_REPLY)
        except Exception:
            log.exception("WhatsApp fallback reply failed | phone=%s", phone_number[:6] + "****")
    finally:
        db.close()
        if ctx_token is not None:
            _wa_graph_phone_id.reset(ctx_token)


async def _process_media_message(
    phone_number: str,
    media_id: str,
    graph_phone_number_id: str = "",
    meta_message_id: str = "",
    inbound_message_type: str = "image",
) -> None:
    """Handle an incoming media file — either as a job submission or crew doc upload."""
    ctx_token = _wa_graph_phone_id.set(graph_phone_number_id) if graph_phone_number_id else None
    db = SessionLocal()
    try:
        await _send_typing_indicator(meta_message_id)
        _record_whatsapp_message(
            phone_number,
            "inbound",
            inbound_message_type,
            f"[{inbound_message_type}] {media_id}".strip(),
            meta_message_id=meta_message_id,
            graph_phone_number_id=graph_phone_number_id,
            payload={"media_id": media_id} if media_id else None,
        )
        wa_session = _get_or_create_session(phone_number, db)

        if wa_session.mode == "job_submit":
            if not media_id:
                await _send_whatsapp(
                    phone_number,
                    "⚠️ Please send a *screenshot image* (PNG, JPEG, WebP) or paste the *job text* instead.",
                )
                return
            try:
                if not settings.OPENAI_API_KEY:
                    await _send_whatsapp(phone_number, "⚠️ AI processing is temporarily unavailable. Try again soon.")
                else:
                    await _send_job_review_wait(phone_number, "image")
                    # The ack cleared the typing bubble — bring it back for the
                    # slow download + AI scan that follows.
                    await _send_typing_indicator(meta_message_id)
                    await _process_job_image_submission(phone_number, media_id, db)
                await _send_whatsapp_buttons(
                    phone_number,
                    "What's next?\n\n_Reply *balance* anytime._",
                    [("btn_submit_job", "Submit Another"), ("btn_find_matches", "Matches (1 token)"), ("btn_menu", "Menu")],
                )
            finally:
                wa_session.mode = "chat"
                db.commit()
            return

        link = _make_magic_link(phone_number, db)
        await _send_whatsapp_cta_url(
            phone_number,
            header="Upload Crew Documents 📎",
            body=(
                "To upload your CV, passport, STCW, certs etc. tap the button below.\n\n"
                "_💡 Tip: Want to submit a job posting? Type *submit job* first, then send the screenshot._"
            ),
            button_text="Upload docs",
            url_link=link,
            footer=_link_expiry_note().strip("_"),
        )
    except Exception as exc:
        log.exception("WhatsApp media handler error | phone=%s | %s", phone_number[:6] + "****", exc)
    finally:
        db.close()
        if ctx_token is not None:
            _wa_graph_phone_id.reset(ctx_token)


_MAINTENANCE_MESSAGE = (
    "🛠️ *CARVER is down for maintenance*\n\n"
    "We're really sorry — the service is temporarily offline while we make "
    "some improvements. We'll only be down for a few days.\n\n"
    "As a thank-you for waiting, we'll reward you when we're back. 🎁\n\n"
    "See you soon! ⚓"
)


async def _send_stale_notice(phone_number: str, graph_phone_number_id: str = "") -> None:
    """Tell a user their message landed too late to process, instead of dropping it."""
    ctx_token = _wa_graph_phone_id.set(graph_phone_number_id) if graph_phone_number_id else None
    try:
        await _send_whatsapp(phone_number, _STALE_NOTICE)
    except Exception as exc:
        log.exception("WhatsApp stale notice error | phone=%s | %s", phone_number[:6] + "****", exc)
    finally:
        if ctx_token is not None:
            _wa_graph_phone_id.reset(ctx_token)


async def _send_maintenance_notice(
    phone_number: str,
    message_type: str = "text",
    graph_phone_number_id: str = "",
    meta_message_id: str = "",
) -> None:
    """Reply to any inbound message with the maintenance notice (maintenance mode only)."""
    ctx_token = _wa_graph_phone_id.set(graph_phone_number_id) if graph_phone_number_id else None
    try:
        _record_whatsapp_message(
            phone_number,
            "inbound",
            message_type or "unknown",
            "",
            meta_message_id=meta_message_id,
            graph_phone_number_id=graph_phone_number_id,
            payload={"reason": "maintenance_mode"},
        )
        await _send_whatsapp(phone_number, _MAINTENANCE_MESSAGE)
    except Exception as exc:
        log.exception("WhatsApp maintenance notice error | phone=%s | %s", phone_number[:6] + "****", exc)
    finally:
        if ctx_token is not None:
            _wa_graph_phone_id.reset(ctx_token)


@router.post("/webhooks/whatsapp", status_code=status.HTTP_200_OK)
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive incoming WhatsApp messages from Meta.

    Parses the payload synchronously, then schedules processing as a background
    task so Meta always gets a 200 within milliseconds — even for slow operations
    like AI matching which can take 30-60 seconds.
    """
    if not flags.is_enabled("whatsapp"):
        metrics.increment("feature_blocked")
        return {"ok": False}

    if not _wa_configured():
        log.warning("WhatsApp webhook hit but credentials not configured")
        raise HTTPException(status_code=503, detail="WhatsApp not configured")

    body_bytes = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_meta_signature(body_bytes, sig):
        log.warning("WhatsApp webhook signature invalid")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        data = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Parse only — no DB, no I/O. Schedule all processing as a background task.
    try:
        entry = (data.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value = change.get("value") or {}
        metadata = value.get("metadata") or {}
        recipient_phone_number_id = str(metadata.get("phone_number_id") or "").strip()
        recipient_display_number = str(metadata.get("display_phone_number") or "").strip()

        allowed_ids = settings.WHATSAPP_PHONE_NUMBER_IDS
        if recipient_phone_number_id and allowed_ids and recipient_phone_number_id not in allowed_ids:
            log.warning(
                "WhatsApp webhook ignored for different recipient | allowed=%s | recipient_id=%s | recipient=%s",
                ",".join(allowed_ids),
                recipient_phone_number_id,
                recipient_display_number or "?",
            )
            return {"ok": True}

        graph_phone_number_id = recipient_phone_number_id or (allowed_ids[0] if allowed_ids else "")

        # Delivery receipts ride the same webhook but never the message
        # pipeline — a status-only callback is parsed, queued, and 200'd.
        statuses = value.get("statuses") or []
        if statuses:
            background_tasks.add_task(_process_status_callbacks, statuses)

        messages = value.get("messages") or []
        if not messages:
            return {"ok": True}

        for msg in messages:
            msg_type = msg.get("type", "")
            phone_number = msg.get("from", "")
            msg_id = msg.get("id", "")
            msg_timestamp = msg.get("timestamp")

            if not phone_number:
                continue

            skip_reason = _inbound_skip_reason(msg_id, msg_timestamp) if msg_id else None
            if skip_reason == "stale":
                # Status callbacks arrive with no `messages` array and never
                # reach this loop, so only a real user message is answered here.
                if msg_type == "text" and _should_notify_stale(phone_number):
                    background_tasks.add_task(
                        _send_stale_notice, phone_number, graph_phone_number_id,
                    )
                continue
            if skip_reason:
                continue

            if settings.WHATSAPP_MAINTENANCE_MODE:
                background_tasks.add_task(
                    _send_maintenance_notice, phone_number, msg_type, graph_phone_number_id, msg_id,
                )
                continue

            if msg_type == "text":
                user_text = (msg.get("text") or {}).get("body", "").strip()
                if not user_text:
                    background_tasks.add_task(
                        _record_unsupported_inbound_whatsapp_message,
                        phone_number,
                        "text",
                        graph_phone_number_id,
                        msg_id,
                        reason="empty_text",
                    )
                    continue
            elif msg_type == "interactive":
                interactive = msg.get("interactive") or {}
                itype = interactive.get("type", "")
                if itype == "button_reply":
                    bid = (interactive.get("button_reply") or {}).get("id", "")
                elif itype == "list_reply":
                    bid = (interactive.get("list_reply") or {}).get("id", "")
                else:
                    background_tasks.add_task(
                        _record_unsupported_inbound_whatsapp_message,
                        phone_number,
                        "interactive",
                        graph_phone_number_id,
                        msg_id,
                        reason=f"unsupported_interactive:{itype or 'unknown'}",
                    )
                    continue
                if bid.startswith("buy_") and bid[4:].isdigit():
                    # Token-pack picks are config-driven (settings.TOKEN_PACKAGES),
                    # so they can't live in the static command map.
                    user_text = f"buy pack {bid[4:]}"
                else:
                    user_text = _INTERACTIVE_CMD_MAP.get(bid, "help")
            elif msg_type == "image":
                media_id = (msg.get("image") or {}).get("id", "")
                if media_id:
                    background_tasks.add_task(_process_media_message, phone_number, media_id, graph_phone_number_id, msg_id, "image")
                continue
            elif msg_type in ("document", "audio", "video"):
                background_tasks.add_task(_process_media_message, phone_number, "", graph_phone_number_id, msg_id, msg_type)
                continue
            else:
                background_tasks.add_task(
                    _record_unsupported_inbound_whatsapp_message,
                    phone_number,
                    msg_type or "unknown",
                    graph_phone_number_id,
                    msg_id,
                    reason="unsupported_message_type",
                )
                continue

            background_tasks.add_task(_process_whatsapp_message, phone_number, user_text, graph_phone_number_id, msg_id, msg_type)

    except Exception as exc:
        log.exception("WhatsApp webhook parse error | %s", exc)

    return {"ok": True}


@router.get("/wa/auth/{token}")
async def whatsapp_magic_auth(token: str, request: Request, response: Response, db: Session = Depends(get_db)):
    """Validate a WhatsApp magic link token and issue a session cookie.

    Tokens are reusable within their TTL — clicking the same link twice works
    as long as it hasn't expired.
    """
    if len(token) > 64:
        raise HTTPException(status_code=400, detail="Invalid token")

    record = db.query(WhatsAppMagicToken).filter(WhatsAppMagicToken.token == token).first()
    if not record:
        raise HTTPException(status_code=404, detail="Link not found.")
    now = datetime.now(timezone.utc)
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        raise HTTPException(status_code=410, detail="This link has expired. Send any message on WhatsApp to get a new one.")

    session_token = issue_session_token({"sub": record.phone_number, "role": "crew", "provider": "whatsapp"})
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=session_token,
        httponly=True,
        secure=settings.SESSION_SECURE_COOKIE,
        samesite="none" if settings.SESSION_SECURE_COOKIE else "lax",
        max_age=settings.SESSION_TTL_SECONDS,
        path="/",
    )
    # Primary: DB-stored redirect.  Fallback: ?r= query param from the magic link URL.
    redirect = record.redirect_to if _is_safe_redirect(record.redirect_to) else None
    if not redirect:
        qp = request.query_params.get("r", "")
        redirect = qp if _is_safe_redirect(qp) else "/profile"
    if not record.used:
        try:
            record.used = True
            record.used_at = now
            db.commit()
        except Exception:
            db.rollback()
            log.warning("Failed to mark magic token used | phone=%s", record.phone_number[:6] + "****")
    log.info("WhatsApp magic auth success | phone=%s | redirect=%s | db_redirect=%s",
             record.phone_number[:6] + "****", redirect, record.redirect_to)
    metrics.increment("whatsapp_magic_logins")
    record_server_event(record.phone_number, "magic_login", redirect)
    return {"ok": True, "redirect": redirect, "session_token": session_token}
