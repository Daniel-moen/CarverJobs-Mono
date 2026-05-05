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

import hashlib
import hmac
import json
import secrets
import threading
import time
import urllib.request
from contextvars import ContextVar
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app import flags, metrics
from app.database import SessionLocal, get_db
from app.logger import get_logger
from app.models import CrewProfile, Document, Job, JobHistoryEntry, MatchSession, MatchSessionResult, WhatsAppMagicToken, WhatsAppMessage, WhatsAppSession
from app.security import issue_session_token
from app.settings import settings
from app.services.ai_client import AIClientError, _posthog_config
from app.services.credits import add_credits, get_credit_balance, is_subscribed, spend_credits
from app.services.feedback_settings import feedback_is_eligible

log = get_logger("carver.whatsapp")

router = APIRouter(tags=["whatsapp"])
_http = httpx.AsyncClient(timeout=20.0)

# ── Deduplication ─────────────────────────────────────────────────────────────
# Keep the last 500 processed Meta message IDs in memory.
# Prevents duplicate sends when Meta retries a webhook (e.g. after server restart).
_SEEN_MSG_IDS: set[str] = set()
_SEEN_MSG_IDS_ORDER: list[str] = []
_SEEN_MSG_MAX = 500
_STALE_MSG_SECONDS = 300  # ignore messages older than 5 minutes
_ACTIVE_MATCH_RUNS: set[str] = set()
_ACTIVE_MATCH_RUNS_LOCK = threading.Lock()
_MATCH_SCOPE_ALL = "all"
_MATCH_SCOPE_RECENT = "recent"
_POSTHOG_CAPTURE_TIMEOUT = 2


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


def _is_duplicate_or_stale(msg_id: str, timestamp_str: str | None) -> bool:
    """Return True (and skip processing) if the message was already handled or is too old."""
    # Only stale-drop messages when the timestamp clearly maps to a real Unix
    # epoch. If Meta sends an unexpected format, process it normally.
    msg_ts = _parse_meta_timestamp(timestamp_str)
    if msg_ts is not None:
        age = time.time() - msg_ts
        if age > _STALE_MSG_SECONDS:
            log.warning("WhatsApp stale message skipped | id=%s | age=%.0fs", msg_id, age)
            return True

    # Duplicate check
    if msg_id in _SEEN_MSG_IDS:
        log.warning("WhatsApp duplicate message skipped | id=%s", msg_id)
        return True

    _SEEN_MSG_IDS.add(msg_id)
    _SEEN_MSG_IDS_ORDER.append(msg_id)
    if len(_SEEN_MSG_IDS_ORDER) > _SEEN_MSG_MAX:
        oldest = _SEEN_MSG_IDS_ORDER.pop(0)
        _SEEN_MSG_IDS.discard(oldest)

    return False


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

_GRAPH_URL = "https://graph.facebook.com/v19.0"

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

def _posthog_whatsapp_distinct_id(phone_number: str) -> str:
    """Stable, non-reversible distinct id for WhatsApp users."""
    raw = f"{settings.SECRET_KEY}:{phone_number}".encode()
    return "whatsapp:" + hashlib.sha256(raw).hexdigest()[:24]


def _capture_whatsapp_posthog_event(
    phone_number: str,
    direction: str,
    message_type: str,
    content: str | None,
    *,
    meta_message_id: str | None = None,
    graph_phone_number_id: str | None = None,
    payload: dict | None = None,
) -> None:
    """Best-effort PostHog channel event for WhatsApp traffic; never sends message text."""
    api_key, host, _capture_content = _posthog_config()
    if not api_key:
        return

    event_name = "whatsapp_message_received" if direction == "inbound" else "whatsapp_message_sent"
    payload = payload or {}
    status_code = payload.get("status_code")
    properties = {
        "distinct_id": _posthog_whatsapp_distinct_id(phone_number),
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
    body = {
        "api_key": api_key,
        "event": event_name,
        "properties": {key: value for key, value in properties.items() if value is not None},
    }
    req = urllib.request.Request(
        f"{host}/i/v0/e/",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_POSTHOG_CAPTURE_TIMEOUT):
            pass
    except Exception as exc:
        log.debug("PostHog WhatsApp capture failed | direction=%s | type=%s | error=%s", direction, message_type, exc)


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
    _capture_whatsapp_posthog_event(
        phone_number,
        direction,
        message_type,
        content,
        meta_message_id=meta_message_id,
        graph_phone_number_id=graph_phone_number_id,
        payload=payload,
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
    url = _messages_url()
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}
    audit_payload: dict = {"graph_phone_number_id": _active_wa_phone_number_id()}
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
            graph_phone_number_id=_active_wa_phone_number_id(),
            payload=audit_payload,
        )


async def _send_whatsapp_buttons(to: str, body: str, buttons: list[tuple[str, str]]) -> None:
    """Send an interactive quick-reply button message (up to 3 buttons)."""
    url = _messages_url()
    btn_list = [
        {"type": "reply", "reply": {"id": bid, "title": title[:20]}}
        for bid, title in buttons[:3]
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
        "graph_phone_number_id": _active_wa_phone_number_id(),
        "buttons": [{"id": bid, "title": title[:20]} for bid, title in buttons[:3]],
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
            graph_phone_number_id=_active_wa_phone_number_id(),
            payload=audit_payload,
        )


async def _send_job_review_wait(to: str) -> None:
    """Interim message while AI reviews a job submission (text or image)."""
    await _send_whatsapp(
        to,
        "⏳ Reading your posting… this can take a moment.",
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
    return (
        f"💳 *Your balance: {balance} {w}.*\n"
        "Each *Find Matches* run uses 1 token. "
        "Submit a valid job to earn tokens, or type *buy tokens* to top up."
    )


def _credits_standalone_message(balance: int, subscribed: bool = False) -> str:
    """Full explainer for *balance* / *tokens* text commands."""
    return (
        _credits_summary_for_menu(balance, subscribed)
        + "\n\n"
        + "_Type *help* for the full menu._"
    )


async def _send_help_menu(to: str, db: Session) -> None:
    """Send interactive list menu with all available commands."""
    balance = get_credit_balance(db, to)
    sub = is_subscribed(db, to)
    body_text = f"What would you like to do?\n\n{_credits_summary_for_menu(balance, sub)}"
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
    credits_balance = add_credits(db, phone_number, amount=1)

    metrics.increment("whatsapp_job_submissions")
    title = job.title or "Yacht Crew Position"
    role = job.role or "Crew"
    location = job.location or "Unknown"
    await _send_whatsapp(
        phone_number,
        f"✅ *Job posted to the board!*\n\n"
        f"⚓ *{title}*\n"
        f"🧑‍✈️ Role: {role}\n"
        f"📍 Location: {location}\n\n"
        f"You earned *1 token* for sharing this job.\n"
        f"Current balance: *{credits_balance}* token{'s' if credits_balance != 1 else ''}.\n\n"
        f"_The listing is now live for crew to see._",
    )


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
    credits_balance = add_credits(db, phone_number, amount=1)

    metrics.increment("whatsapp_job_submissions")
    title = job.title or "Yacht Crew Position"
    role = job.role or "Crew"
    location = job.location or "Unknown"
    await _send_whatsapp(
        phone_number,
        f"✅ *Job posted to the board!*\n\n"
        f"⚓ *{title}*\n"
        f"🧑‍✈️ Role: {role}\n"
        f"📍 Location: {location}\n\n"
        f"You earned *1 token* for sharing this job.\n"
        f"Current balance: *{credits_balance}* token{'s' if credits_balance != 1 else ''}.\n\n"
        f"_The listing is now live for crew to see._",
    )


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


_ALLOWED_REDIRECTS = frozenset({
    "/profile", "/jobs", "/status", "/", "/subscription", "/?feedback=1",
})
_ALLOWED_REDIRECT_PREFIXES = ("/matches/",)


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
    return session


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


async def _send_feedback_request(phone: str, db: Session) -> None:
    link = _make_magic_link(phone, db, redirect_to="/?feedback=1")
    await _send_whatsapp(
        phone,
        "💬 *Quick feedback required*\n\n"
        "Please complete this short feedback form about your CARVER experience. "
        "We'll add *2 tokens* to your account when you submit it.\n\n"
        f"Feedback form: {link}\n\n"
        "_Takes less than 2 minutes. Reward available once per user._",
    )


# ── AI helpers ────────────────────────────────────────────────────────────────

REQUIRED_ONBOARD_FIELDS = [
    "firstName", "lastName", "sex", "desiredRole", "yearsExperience",
    "nationality", "currentLocation", "preferredLocations",
    "contractType", "salaryMin", "salaryMax", "certifications", "languages",
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
    return f"""You are CARVER — an energetic, knowledgeable crew agent who lives and breathes superyachts.
You're chatting on WhatsApp to build a new crew member's profile. Think of yourself as a friendly Chief Stew or Bosun welcoming someone to the fleet.

Your vibe: warm, upbeat, uses maritime lingo naturally (crew, vessel, galley, bridge, charter season, Med, etc.). You celebrate each answer with a short reaction before the next question — keep it genuine, not robotic.

Profile so far ({filled}/{len(REQUIRED_ONBOARD_FIELDS)} fields):
{json.dumps(profile, ensure_ascii=True)}

Still missing: {missing_text}

Review the conversation history. NEVER re-ask something already answered.
Ask about fields in this order when missing:
  1. firstName + lastName (ask together)
  2. sex (Male, Female, Other, or Prefer not to say)
  3. desiredRole (e.g. Chief Stew, Bosun, Engineer, Chef, Captain, Deckhand)
  4. yearsExperience (years in yachting or maritime)
  5. nationality
  6. currentLocation (city / country)
  7. preferredLocations (cruising grounds: Med, Caribbean, etc.)
  8. contractType (Permanent, Seasonal, Rotational, or Temporary)
  9. salaryMin + salaryMax (ask together: monthly EUR)
  10. certifications (STCW, ENG1, Yachtmaster, PYA, etc.)
  11. languages spoken

Style rules for WhatsApp:
- Use *bold* for emphasis (WhatsApp markdown).
- Use emojis naturally but don't overdo it — 1-2 per message max.
- Keep messages punchy (2-4 sentences). WhatsApp is a chat, not an email.
- React to their answer first ("Nice!", "Solid experience!", "Love the Med!") then ask the next thing.
- When nearly done, build excitement ("Almost there!", "One more and you're set!").
- When all done, celebrate big — they just joined the fleet.

First reply only (empty conversation history in the messages you receive):
- Include exactly one brief sentence explaining tokens: Each *Find Matches* run uses *1 token*. Submit a valid job to earn tokens, or type *buy tokens* to top up.

Data rules:
- ONLY set "done": true when ALL 13 fields are collected (missing list is empty).
- Only populate update fields when the user clearly provided that info.
- Do not invent or assume any facts.
- Keep values short and clean (e.g. nationality: "British", contractType: "Seasonal").
- For salaryMin/salaryMax use numeric strings only (e.g. "4000", "6000").
- If the user wants to skip a field, set it to "unknown" so it counts as filled.

Return strict JSON only:
{{"message": "your reply", "done": {str(all_done).lower()}, "updates": {{"firstName": "", "lastName": "", "sex": "", "desiredRole": "", "yearsExperience": "", "nationality": "", "currentLocation": "", "preferredLocations": "", "contractType": "", "salaryMin": "", "salaryMax": "", "certifications": "", "languages": ""}}}}

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

    missing = [f for f in REQUIRED_ONBOARD_FIELDS if not str(partial.get(f, "")).strip()]
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


# ── Profile helpers ───────────────────────────────────────────────────────────

def _apply_updates(partial: dict, updates: dict) -> dict:
    """Merge non-empty AI updates into the partial profile dict."""
    for k, v in updates.items():
        if isinstance(v, str) and v.strip():
            partial[k] = v.strip()
    return partial


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


# ── Command handlers ──────────────────────────────────────────────────────────

async def _handle_profile_command(phone_number: str, db: Session) -> str:
    profile = db.query(CrewProfile).filter(CrewProfile.user_key == phone_number).first()
    bal = get_credit_balance(db, phone_number)
    tok_w = "token" if bal == 1 else "tokens"
    token_line = f"\n\n💳 *Tokens:* {bal} {tok_w} — each *Find Matches* uses 1; submit a job to earn 1."
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


async def _handle_jobs_command(phone_number: str, db: Session) -> str:
    link = _make_magic_link(phone_number, db, redirect_to="/jobs")
    return (
        "🔎 *Browse Open Yacht Positions*\n\n"
        "View all live superyacht crew roles — deck, interior, engineering & more:\n\n"
        f"👉 {link}\n\n"
        "_Link expires in 30 minutes._"
    )


def _normalise_match_scope(match_scope: str | None) -> str:
    return _MATCH_SCOPE_RECENT if match_scope == _MATCH_SCOPE_RECENT else _MATCH_SCOPE_ALL


async def _handle_match_command(phone_number: str, db: Session, match_scope: str = _MATCH_SCOPE_ALL) -> None:
    """Run the AI matching engine, save results, and send a website link.

    Results are persisted as a MatchSession so the user can view all matches
    and draft application emails on the website.
    """
    import math as _math

    from app.services.matching_engine import (
        CandidateProfile,
        JobSummary,
        match_candidate_to_jobs,
    )

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
    jobs_query = (
        db.query(Job)
        .filter(Job.status.in_(["open", "priority"]))
    )
    scope_label = "all database jobs"
    if match_scope == _MATCH_SCOPE_RECENT:
        recent_days = max(1, settings.WA_MATCH_RECENT_DAYS)
        cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
        jobs_query = jobs_query.filter(Job.created_at >= cutoff)
        scope_label = f"recent posts from the last {recent_days} day{'s' if recent_days != 1 else ''}"

    all_jobs = jobs_query.order_by(Job.created_at.desc()).all()
    if not all_jobs:
        if match_scope == _MATCH_SCOPE_RECENT:
            await _send_whatsapp(
                phone_number,
                "No recent open yacht positions are in the database yet — try *All DB Jobs* instead.",
            )
            await _send_match_scope_menu(phone_number)
        else:
            await _send_whatsapp(phone_number, "No open yacht positions are in the database right now — check back soon!")
        return

    credits_remaining = spend_credits(db, phone_number, amount=1)
    if credits_remaining is None:
        current_credits = get_credit_balance(db, phone_number)
        await _send_whatsapp(
            phone_number,
            "⚠️ You need *1 token* to run matching.\n\n"
            "Submit a job to earn tokens, or type *buy tokens* to top up.\n"
            f"Current balance: *{current_credits}* token{'s' if current_credits != 1 else ''}.",
        )
        await _send_whatsapp_buttons(
            phone_number,
            "What would you like to do?",
            [("btn_submit_job", "Submit Job"), ("cmd_subscribe", "Buy Tokens"), ("btn_menu", "Menu")],
        )
        return

    _BATCH_SIZE = 10
    _AVG_SECS_PER_BATCH = 8
    num_batches = _math.ceil(len(all_jobs) / _BATCH_SIZE)
    est_secs = num_batches * _AVG_SECS_PER_BATCH
    est_str = f"~{est_secs}s" if est_secs < 60 else f"~{round(est_secs / 60)} min"

    tok_left = "token" if credits_remaining == 1 else "tokens"
    await _send_whatsapp(
        phone_number,
        f"💳 *1 token used* — *{credits_remaining}* {tok_left} left.\n\n"
        f"⏳ Scanning *{len(all_jobs)} positions* from *{scope_label}* ({est_str}) — hang tight!",
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

    job_summaries = [
        JobSummary(
            job_id=j.id, title=j.title, role=j.role or "", department=j.department or "",
            location=j.location, yacht_type=j.yacht_type or "", yacht_length_m=j.yacht_length_m,
            start_date=j.start_date or "", contract_type=j.contract_type or "",
            rotation=j.rotation or "", season=j.season or "",
            salary_min=j.salary_min, salary_max=j.salary_max,
            salary_currency=j.salary_currency or "EUR",
            experience_required_years=j.experience_required_years,
            certifications_required=j.certifications_required or "",
            languages_required=j.languages_required or "",
            description=j.description or "",
            status=j.status or "open",
        )
        for j in all_jobs
    ]
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
        credits_remaining = add_credits(db, phone_number, amount=1)
        await _send_whatsapp(phone_number, "⚠️ Matching hit a snag — try again in a moment.")
        return

    matched = [r for r in (results or []) if r.matched]
    if not matched:
        await _send_whatsapp(
            phone_number,
            "No strong matches right now. A complete profile with certs and docs boosts your chances!",
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

    # Build brief summary for WhatsApp (top 3)
    top = matched[:3]
    lines = [f"🎯 *Found {len(matched)} match{'es' if len(matched) != 1 else ''}!*\n"]
    lines.append(f"_Scanned {scope_label}._\n")
    for i, m in enumerate(top, 1):
        job = jobs_by_id.get(m.job_id)
        if not job:
            continue
        compat = int(m.compatibility)
        lines.append(f"{i}. *{job.title}* — {job.location} ({compat}%)")
    if len(matched) > 3:
        lines.append(f"   _...and {len(matched) - 3} more_")

    # Magic link to the match session page
    link = _make_magic_link(phone_number, db, redirect_to=f"/matches/{match_session.id}")
    lines.append(f"\nView all matches & draft applications:\n👉 {link}")
    lines.append("_Link expires in 30 min._")
    lines.append(f"\nTokens remaining: *{credits_remaining}*")

    await _send_whatsapp(phone_number, "\n".join(lines))

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



# ── Onboarding flow ───────────────────────────────────────────────────────────

_FALLBACK_GREETING = (
    "Ahoy! 🛥️ Welcome to *CARVER* — your fast track to superyacht crew positions.\n\n"
    "I'm going to build your crew profile in a quick chat — takes about 2 minutes "
    "and gets you in front of recruiters and vessels straight away.\n\n"
    "💳 *Tokens:* Each *Find Matches* uses *1 token*. Submit a valid job to earn tokens, or type *buy tokens* to top up.\n\n"
    "Let's start with the basics — what's your *full name*? 🪪"
)


async def _run_onboarding(wa_session: WhatsAppSession, user_message: str, db: Session) -> str:
    history = json.loads(wa_session.history)
    partial = json.loads(wa_session.partial_profile)

    system = _build_onboard_system(partial)
    parsed = await _call_openai(system, history, user_message)

    # First message: use AI greeting, fall back to static if AI fails
    if not history:
        message = (parsed.get("message") or "").strip() or _FALLBACK_GREETING
        updates = parsed.get("updates") if isinstance(parsed.get("updates"), dict) else {}
        clean_updates = {k: str(v).strip() for k, v in updates.items() if isinstance(k, str) and v and str(v).strip()}
        partial = _apply_updates(partial, clean_updates)
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": message})
        _save_session(wa_session, db, history, partial)
        return message

    # parsed already populated above for non-first messages

    message = (parsed.get("message") or "").strip()
    done = bool(parsed.get("done"))
    updates = parsed.get("updates") if isinstance(parsed.get("updates"), dict) else {}
    clean_updates = {k: str(v).strip() for k, v in updates.items() if isinstance(k, str) and v and str(v).strip()}

    # When the LLM completely fails, try basic extraction from the user's message
    # so the conversation can still make progress.
    llm_failed = not parsed
    if llm_failed:
        clean_updates = _fallback_extract(partial, user_message)
        log.warning("LLM failed — fallback extraction | updates=%s", clean_updates)

    partial = _apply_updates(partial, clean_updates)

    if not message:
        missing = [f for f in REQUIRED_ONBOARD_FIELDS if not str(partial.get(f, "")).strip()]
        filled = len(REQUIRED_ONBOARD_FIELDS) - len(missing)
        if missing:
            question = _FIELD_QUESTIONS.get(missing[0], f"Could you tell me your {_FIELD_LABELS.get(missing[0], missing[0])}?")
            if clean_updates:
                _acks = ["Nice one! ✅", "Got it, thanks! 👍", "Solid — noted! ✅", "Great stuff! 🙌"]
                ack = _acks[filled % len(_acks)]
                if filled >= 9:
                    message = f"{ack} Almost there — just a couple more! {question}"
                else:
                    message = f"{ack} {question}"
            else:
                message = f"Hmm, didn't quite catch that — no worries! {question}"
        else:
            message = "That's a wrap — your crew profile is *complete*! 🎉"
            done = True

    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": message})

    if done:
        _save_profile_to_db(wa_session.phone_number, partial, db)
        _save_session(wa_session, db, history, partial, mode="chat")
        metrics.increment("onboard_completed")
        link = _make_magic_link(wa_session.phone_number, db)
        name = partial.get("firstName", "crew")
        message += (
            f"\n\n✅ *Interview complete* — we saved your answers as your crew profile.\n\n"
            f"🎉 *Welcome to the fleet, {name}!*\n\n"
            f"Your profile is live and ready to match with vessels. "
            f"To really stand out, upload your docs — CV, passport, STCW & certs:\n\n"
            f"👉 {link}\n\n"
            f"💳 *Tokens:* Each *Find Matches* run uses *1 token* — "
            f"submit a valid job to earn tokens, or type *buy tokens* to top up.\n\n"
            f"_Link expires in 30 min. Type *help* anytime to see what I can do for you._ ⚡"
        )
    else:
        _save_session(wa_session, db, history, partial)

    return message


# ── Chat / interview flow ─────────────────────────────────────────────────────

async def _run_chat(wa_session: WhatsAppSession, user_message: str, db: Session) -> str | None:
    """Route a command. Returns a reply string, or None if the handler sent messages itself."""
    cmd = user_message.strip().lower()
    phone = wa_session.phone_number

    if cmd in ("help", "commands", "menu", "hi", "hello"):
        await _send_help_menu(phone, db)
        return None

    if cmd in ("credits", "balance", "my credits", "tokens", "my tokens"):
        bal = get_credit_balance(db, phone)
        await _send_whatsapp(phone, _credits_standalone_message(bal))
        return None
    if cmd in ("feedback", "give feedback", "review", "survey"):
        eligible, _setting = feedback_is_eligible(db, user_key=phone, source="whatsapp_message")
        if not eligible:
            await _send_whatsapp(
                phone,
                "💬 Feedback rewards are not open for your account right now. Type *help* to see what else you can do.",
            )
            return None
        await _send_feedback_request(phone, db)
        return None

    if cmd in ("subscribe", "pro", "upgrade", "paid", "subscription", "buy tokens", "buy", "top up", "topup"):
        link = _make_magic_link(phone, db, redirect_to="/subscription")
        bal = get_credit_balance(db, phone)
        w = "token" if bal == 1 else "tokens"
        await _send_whatsapp(
            phone,
            f"🪙 *Buy Tokens*\n\n"
            f"Your balance: *{bal} {w}*\n\n"
            f"Token packs available:\n"
            f"• *10 tokens* — R100\n"
            f"• *20 tokens* — R200\n\n"
            f"👉 {link}\n\n"
            "_Link expires in 30 minutes._",
        )
        return None

    if cmd in ("cancel subscription", "cancel pro", "cancel", "unsubscribe"):
        bal = get_credit_balance(db, phone)
        w = "token" if bal == 1 else "tokens"
        link = _make_magic_link(phone, db, redirect_to="/subscription")
        await _send_whatsapp(
            phone,
            f"CARVER is pay-per-token — no recurring plan to cancel.\n\n"
            f"Your balance: *{bal} {w}*.\n\n"
            f"Need more tokens? 👉 {link}",
        )
        await _send_whatsapp_buttons(
            phone,
            "Buy more tokens?",
            [("cmd_subscribe", "Buy Tokens"), ("btn_menu", "Menu")],
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
        await _send_whatsapp(
            phone,
            text + f"\n\n📎 *Upload or update your crew docs:*\n👉 {link}\n\n_Link expires in 30 minutes._",
        )
        await _send_whatsapp_buttons(
            phone,
            "Need anything else?",
            [("btn_upload_docs", "Upload Docs"), ("btn_find_matches", "Matches (1 token)"), ("btn_menu", "Main Menu")],
        )
        return None

    if cmd in ("upload", "upload docs", "add docs", "add documents"):
        link = _make_magic_link(phone, db)
        await _send_whatsapp(
            phone,
            "📎 *Upload Crew Documents*\n\n"
            "Tap below to upload your CV, passport, STCW, ENG1 & certs — vessels require these for crew:\n\n"
            f"👉 {link}\n\n"
            "_Link expires in 30 minutes._",
        )
        await _send_whatsapp_buttons(
            phone,
            "Anything else?",
            [("btn_view_profile", "View Profile"), ("btn_find_matches", "Matches (1 token)"), ("btn_menu", "Main Menu")],
        )
        return None

    if cmd in ("edit", "edit profile", "update", "update profile", "change profile"):
        link = _make_magic_link(phone, db)
        await _send_whatsapp(
            phone,
            "✏️ *Edit Your Crew Profile*\n\n"
            "Tap below to update your profile — role, experience, certs, salary expectations & more:\n\n"
            f"👉 {link}\n\n"
            "_Link expires in 30 minutes._",
        )
        await _send_whatsapp_buttons(
            phone,
            "Anything else?",
            [("btn_view_profile", "View Profile"), ("btn_find_matches", "Matches (1 token)"), ("btn_menu", "Main Menu")],
        )
        return None

    if cmd in ("jobs", "open jobs", "positions", "vacancies"):
        return await _handle_jobs_command(phone, db)

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
    "cancel subscription", "cancel pro", "cancel", "unsubscribe",
    "help", "commands", "menu",
    "credits", "balance", "my credits", "tokens", "my tokens",
    "feedback", "give feedback", "review", "survey",
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
        _record_whatsapp_message(
            phone_number,
            "inbound",
            inbound_message_type,
            user_text,
            meta_message_id=meta_message_id,
            graph_phone_number_id=graph_phone_number_id,
        )
        wa_session = _get_or_create_session(phone_number, db)
        _cmd = user_text.strip().lower()

        feedback_eligible, _feedback_setting = feedback_is_eligible(db, user_key=phone_number, source="whatsapp_message")
        if (
            feedback_eligible
            and not _feedback_already_submitted(db, phone_number)
            and _cmd not in ("feedback", "give feedback", "review", "survey")
        ):
            await _send_feedback_request(phone_number, db)
            metrics.increment("whatsapp_messages")
            return

        # Global commands bypass onboarding / job-submit modes so the user
        # can always buy tokens, check balance, or open the help menu.
        if wa_session.mode != "chat" and _cmd in _GLOBAL_CMDS:
            reply = await _run_chat(wa_session, user_text, db)
            if reply is not None:
                await _send_whatsapp(phone_number, reply)
            metrics.increment("whatsapp_messages")
            return

        if wa_session.mode == "job_submit":
            # Keep mode until we're done so concurrent image webhooks still see job_submit
            # (otherwise a second photo triggers the crew document upload flow).
            try:
                if not settings.OPENAI_API_KEY:
                    await _send_whatsapp(phone_number, "⚠️ AI processing is temporarily unavailable. Try again soon.")
                else:
                    await _send_job_review_wait(phone_number)
                    await _process_job_text_submission(phone_number, user_text, db)
                await _send_whatsapp_buttons(
                    phone_number,
                    "What's next?\n\n_Reply *balance* anytime._",
                    [("btn_submit_job", "Submit Another"), ("btn_find_matches", "Matches (1 token)"), ("btn_menu", "Menu")],
                )
            finally:
                wa_session.mode = "chat"
                db.commit()
            metrics.increment("whatsapp_messages")
            return

        if wa_session.mode == "onboarding":
            reply = await _run_onboarding(wa_session, user_text, db)
        else:
            reply = await _run_chat(wa_session, user_text, db)
        if reply is not None:
            await _send_whatsapp(phone_number, reply)
        metrics.increment("whatsapp_messages")
    except Exception as exc:
        log.exception("WhatsApp message processing error | phone=%s | %s", phone_number[:6] + "****", exc)
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
                    await _send_job_review_wait(phone_number)
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
        await _send_whatsapp(
            phone_number,
            "📎 *Upload Crew Documents*\n\n"
            "To upload your CV, passport, STCW, certs etc. use the link below:\n\n"
            f"👉 {link}\n\n"
            "_Link expires in 30 minutes._\n\n"
            "_💡 Tip: Want to submit a job posting? Type *submit job* first, then send the screenshot._",
        )
    except Exception as exc:
        log.exception("WhatsApp media handler error | phone=%s | %s", phone_number[:6] + "****", exc)
    finally:
        db.close()
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

            if msg_id and _is_duplicate_or_stale(msg_id, msg_timestamp):
                continue

            if msg_type == "text":
                user_text = (msg.get("text") or {}).get("body", "").strip()
                if not user_text:
                    continue
            elif msg_type == "interactive":
                interactive = msg.get("interactive") or {}
                itype = interactive.get("type", "")
                if itype == "button_reply":
                    bid = (interactive.get("button_reply") or {}).get("id", "")
                elif itype == "list_reply":
                    bid = (interactive.get("list_reply") or {}).get("id", "")
                else:
                    continue
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
    log.info("WhatsApp magic auth success | phone=%s | redirect=%s | db_redirect=%s",
             record.phone_number[:6] + "****", redirect, record.redirect_to)
    metrics.increment("whatsapp_magic_logins")
    return {"ok": True, "redirect": redirect, "session_token": session_token}
