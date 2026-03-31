"""
WhatsApp bot via Meta Cloud API.

Incoming messages → POST /whatsapp/webhook
Webhook verification → GET /whatsapp/webhook
Magic link auth → GET /wa/auth/{token}

Identity: phone number is the user_key used for CrewProfile, Document, JobHistoryEntry.
New users are walked through AI onboarding; existing users get a command router.
Complex actions (doc uploads, full profile edit) are handled via a short-lived magic link
that sets a session cookie and lands the user on the existing web profile page.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app import flags, metrics
from app.database import SessionLocal, get_db
from app.logger import get_logger
from app.models import CrewProfile, Document, Job, JobHistoryEntry, MatchSession, MatchSessionResult, WhatsAppMagicToken, WhatsAppSession
from app.security import issue_session_token
from app.settings import settings

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


def _is_duplicate_or_stale(msg_id: str, timestamp_str: str) -> bool:
    """Return True (and skip processing) if the message was already handled or is too old."""
    # Stale check — Meta timestamp is a Unix epoch string
    try:
        msg_ts = int(timestamp_str)
        age = time.time() - msg_ts
        if age > _STALE_MSG_SECONDS:
            log.warning("WhatsApp stale message skipped | id=%s | age=%.0fs", msg_id, age)
            return True
    except (ValueError, TypeError):
        pass

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

# ── Helpers ──────────────────────────────────────────────────────────────────

_GRAPH_URL = "https://graph.facebook.com/v19.0"


def _wa_configured() -> bool:
    return bool(settings.WHATSAPP_PHONE_NUMBER_ID and settings.WHATSAPP_ACCESS_TOKEN)


def _verify_meta_signature(body: bytes, signature_header: str) -> bool:
    """Verify X-Hub-Signature-256 from Meta."""
    if not settings.META_APP_SECRET:
        # If secret not set, skip verification (development only).
        log.warning("META_APP_SECRET not set — skipping signature verification")
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
    url = f"{_GRAPH_URL}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}
    try:
        resp = await _http.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            log.error("Meta send failed | to=%s | status=%d | body=%s", to, resp.status_code, resp.text[:300])
        else:
            log.info("WhatsApp message sent | to=%s | chars=%d", to, len(text))
    except httpx.HTTPError as exc:
        log.exception("WhatsApp send error | to=%s | %s", to, exc)


async def _send_whatsapp_buttons(to: str, body: str, buttons: list[tuple[str, str]]) -> None:
    """Send an interactive quick-reply button message (up to 3 buttons)."""
    url = f"{_GRAPH_URL}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
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
    try:
        resp = await _http.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            log.error("Meta buttons send failed | to=%s | status=%d | body=%s", to, resp.status_code, resp.text[:300])
    except httpx.HTTPError as exc:
        log.exception("WhatsApp buttons send error | to=%s | %s", to, exc)


async def _send_help_menu(to: str) -> None:
    """Send interactive list menu with all available commands."""
    url = f"{_GRAPH_URL}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": "CARVER 🛥️"},
            "body": {"text": "What would you like to do?"},
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
                            {"id": "cmd_match", "title": "Find Matches", "description": "Match to superyacht roles"},
                            {"id": "cmd_jobs", "title": "Browse Job Board", "description": "View open yacht positions"},
                        ],
                    },
                ],
            },
        },
    }
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}
    try:
        resp = await _http.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            log.error("Meta list send failed | to=%s | status=%d | body=%s", to, resp.status_code, resp.text[:300])
    except httpx.HTTPError as exc:
        log.exception("WhatsApp list send error | to=%s | %s", to, exc)


# Maps interactive button/list reply IDs to plain-text command strings
_INTERACTIVE_CMD_MAP: dict[str, str] = {
    "cmd_profile": "profile",
    "cmd_docs": "docs",
    "cmd_upload": "upload",
    "cmd_edit": "edit",
    "cmd_match": "match",
    "cmd_jobs": "jobs",
    "cmd_help": "help",
    "btn_find_matches": "match",
    "btn_edit_profile": "edit",
    "btn_upload_docs": "upload",
    "btn_view_profile": "profile",
    "btn_help": "help",
    "btn_menu": "help",
}


_ALLOWED_REDIRECTS = frozenset({
    "/profile", "/jobs", "/status", "/", "/subscription",
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
    """
    safe_redirect = redirect_to if _is_safe_redirect(redirect_to) else None
    token = secrets.token_urlsafe(16)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.WA_MAGIC_TOKEN_TTL_SECONDS)
    db.add(WhatsAppMagicToken(
        token=token, phone_number=phone_number,
        expires_at=expires_at, redirect_to=safe_redirect,
    ))
    db.commit()
    return f"{settings.FRONTEND_BASE_URL}/wa/{token}"


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


# ── AI helpers ────────────────────────────────────────────────────────────────

REQUIRED_ONBOARD_FIELDS = [
    "firstName", "lastName", "desiredRole", "yearsExperience",
    "nationality", "currentLocation", "preferredLocations",
    "contractType", "salaryMin", "salaryMax", "certifications", "languages",
]

_FIELD_LABELS: dict[str, str] = {
    "firstName": "full name",
    "lastName": "full name",
    "desiredRole": "desired role",
    "yearsExperience": "years of experience",
    "nationality": "nationality",
    "currentLocation": "current location",
    "preferredLocations": "preferred work locations",
    "contractType": "contract type",
    "salaryMin": "salary expectations",
    "salaryMax": "salary expectations",
    "certifications": "certifications",
    "languages": "languages spoken",
}

_FIELD_QUESTIONS: dict[str, str] = {
    "firstName": "What's your full name?",
    "lastName": "What's your full name?",
    "desiredRole": "What role are you looking for? (e.g. Chief Stew, Bosun, Engineer, Chef)",
    "yearsExperience": "How many years of experience do you have in yachting or maritime?",
    "nationality": "What's your nationality?",
    "currentLocation": "Where are you currently based?",
    "preferredLocations": "Which regions or areas would you prefer to work in?",
    "contractType": "What contract type suits you — Permanent, Seasonal, Rotational, or Temporary?",
    "salaryMin": "What are your monthly salary expectations in EUR (min and max)?",
    "salaryMax": "What are your monthly salary expectations in EUR (min and max)?",
    "certifications": "What certifications do you hold? (STCW, ENG1, Yachtmaster, etc. — or 'none')",
    "languages": "What languages do you speak?",
}


def _build_onboard_system(profile: dict) -> str:
    missing = [f for f in REQUIRED_ONBOARD_FIELDS if not str(profile.get(f, "")).strip()]
    all_done = len(missing) == 0
    seen_labels: set[str] = set()
    readable_missing: list[str] = []
    for f in missing:
        label = _FIELD_LABELS.get(f, f)
        if label not in seen_labels:
            seen_labels.add(label)
            readable_missing.append(label)
    missing_text = ", ".join(readable_missing) if readable_missing else "none — all fields collected!"
    return f"""You are CARVER, a warm and professional onboarding assistant for a superyacht crew platform.
Your sole job: collect every required profile field through natural conversation via WhatsApp.

Profile collected so far:
{json.dumps(profile, ensure_ascii=True)}

Still missing: {missing_text}

Review the conversation history carefully. Do NOT re-ask questions already answered.
Ask about fields in this order when missing:
  1. firstName + lastName (ask together: "What's your full name?")
  2. desiredRole (e.g. Chief Stew, Bosun, Engineer, Chef, Captain)
  3. yearsExperience (years in yachting or maritime)
  4. nationality
  5. currentLocation (city / country they're based in now)
  6. preferredLocations (regions or areas they want to work)
  7. contractType (Permanent, Seasonal, Rotational, or Temporary)
  8. salaryMin + salaryMax (ask together: monthly EUR expectations)
  9. certifications (STCW, ENG1, Yachtmaster, etc. — can say "none" if applicable)
  10. languages spoken

Rules:
- ONLY set "done": true when the missing fields list is empty (all 12 fields collected).
- One question at a time — keep replies short, warm and conversational.
- Use yachting/maritime language where natural (crew, vessel, yacht, deck, etc).
- Only populate update fields when the user has clearly provided that info.
- Do not invent or assume any facts.
- Keep values short and clean (e.g. nationality: "British", contractType: "Seasonal").
- For salaryMin/salaryMax use numeric strings only (e.g. "4000", "6000").
- If the user wants to skip a field, set it to "unknown" so it counts as filled.

Return strict JSON only:
{{"message": "your conversational reply + next question (or warm wrap-up if done)", "done": {str(all_done).lower()}, "updates": {{"firstName": "", "lastName": "", "desiredRole": "", "yearsExperience": "", "nationality": "", "currentLocation": "", "preferredLocations": "", "contractType": "", "salaryMin": "", "salaryMax": "", "certifications": "", "languages": ""}}}}"""


def _build_interview_system(profile: dict) -> str:
    return f"""You are CARVER Interview AI. Ask one concise, practical question at a time.
Your goal: learn candidate preferences for superyacht jobs and suggest profile updates.

Current profile:
{json.dumps(profile, ensure_ascii=True)}

Review conversation history carefully. Do NOT repeat questions already covered.

Return strict JSON only:
{{"message": "your next question or brief acknowledgment + question", "updates": {{"desiredRole": "", "preferredLocations": "", "contractType": "", "rotationPreference": "", "availableFrom": "", "salaryMin": "", "salaryMax": "", "languages": "", "certifications": "", "bio": ""}}}}

Rules:
- Only fill update fields if the user clearly provided that info.
- Keep values short and clean.
- Use yachting/maritime language where natural.
- Do not invent personal facts."""


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
        "firstName": "first_name", "lastName": "last_name",
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
    if not profile:
        return (
            "👋 *Welcome aboard CARVER!*\n\n"
            "You don't have a crew profile yet. Tap *Edit Profile* to set one up — "
            "quick and easy, then you're ready to match with superyacht roles."
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


async def _handle_match_command(phone_number: str, wa_session: WhatsAppSession, db: Session) -> None:
    """Run the AI matching engine, save results, and send a website link.

    Results are persisted as a MatchSession so the user can view all matches
    and draft application emails on the website.
    """
    import asyncio
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

    all_jobs = (
        db.query(Job)
        .filter(Job.status.in_(["open", "priority"]))
        .order_by(Job.created_at.desc())
        .all()
    )
    if not all_jobs:
        await _send_whatsapp(phone_number, "No open yacht positions right now — check back soon!")
        return

    _BATCH_SIZE = 10
    _AVG_SECS_PER_BATCH = 8
    num_batches = _math.ceil(len(all_jobs) / _BATCH_SIZE)
    est_secs = num_batches * _AVG_SECS_PER_BATCH
    est_str = f"~{est_secs}s" if est_secs < 60 else f"~{round(est_secs / 60)} min"

    await _send_whatsapp(
        phone_number,
        f"⏳ Scanning *{len(all_jobs)} positions* ({est_str}) — hang tight!",
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

    await _send_whatsapp(phone_number, "\n".join(lines))



# ── Onboarding flow ───────────────────────────────────────────────────────────

_FALLBACK_GREETING = (
    "Ahoy! 👋 Welcome aboard CARVER — your superyacht crew platform. "
    "Let's build your crew profile in a few quick questions. What's your full name?"
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
        if missing:
            question = _FIELD_QUESTIONS.get(missing[0], f"Could you tell me your {_FIELD_LABELS.get(missing[0], missing[0])}?")
            if clean_updates:
                message = f"Got it, thanks! {question}"
            else:
                message = f"Hmm, I didn't quite catch that. {question}"
        else:
            message = "Perfect — we've got everything we need for your crew profile!"
            done = True

    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": message})

    if done:
        _save_profile_to_db(wa_session.phone_number, partial, db)
        _save_session(wa_session, db, history, partial, mode="chat")
        metrics.increment("onboard_completed")
        link = _make_magic_link(wa_session.phone_number, db)
        message += (
            f"\n\n🎉 *You're all set!*\n\n"
            f"Your crew profile is saved. Tap below to upload your CV, passport, STCW & certs — "
            f"recruiters love a complete file and it helps you stand out:\n\n"
            f"👉 {link}\n\n"
            f"_Link expires in 30 minutes._"
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
        await _send_help_menu(phone)
        return None

    if cmd in ("profile", "my profile", "show profile"):
        text = await _handle_profile_command(phone, db)
        await _send_whatsapp(phone, text)
        await _send_whatsapp_buttons(
            phone,
            "What's next?",
            [("btn_edit_profile", "Edit Profile"), ("btn_find_matches", "Find Matches"), ("btn_menu", "Main Menu")],
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
            [("btn_upload_docs", "Upload Docs"), ("btn_find_matches", "Find Matches"), ("btn_menu", "Main Menu")],
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
            [("btn_view_profile", "View Profile"), ("btn_find_matches", "Find Matches"), ("btn_menu", "Main Menu")],
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
            [("btn_view_profile", "View Profile"), ("btn_find_matches", "Find Matches"), ("btn_menu", "Main Menu")],
        )
        return None

    if cmd in ("jobs", "open jobs", "positions", "vacancies"):
        return await _handle_jobs_command(phone, db)

    if cmd in ("match", "find jobs", "find matches", "matching", "find me jobs", "job match"):
        await _handle_match_command(phone, wa_session, db)
        return None

    # Unrecognised input → show the menu
    await _send_help_menu(phone)
    return None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/whatsapp/webhook", response_class=PlainTextResponse)
async def whatsapp_verify(request: Request):
    """Meta webhook verification handshake."""
    params = request.query_params
    if params.get("hub.verify_token") == settings.META_VERIFY_TOKEN:
        log.info("WhatsApp webhook verified")
        return PlainTextResponse(params.get("hub.challenge", ""))
    log.warning("WhatsApp webhook verification failed — token mismatch")
    raise HTTPException(status_code=403, detail="Verification failed")


async def _process_whatsapp_message(phone_number: str, user_text: str) -> None:
    """Handle a parsed WhatsApp message in the background (owns its own DB session)."""
    db = SessionLocal()
    try:
        wa_session = _get_or_create_session(phone_number, db)
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


async def _process_media_upload(phone_number: str) -> None:
    """Send an upload magic link in response to a received media file."""
    db = SessionLocal()
    try:
        link = _make_magic_link(phone_number, db)
        await _send_whatsapp(
            phone_number,
            "📎 *Upload Crew Documents*\n\n"
            "To upload your CV, passport, STCW, certs etc. use the link below:\n\n"
            f"👉 {link}\n\n"
            "_Link expires in 30 minutes._",
        )
    except Exception as exc:
        log.exception("WhatsApp media handler error | phone=%s | %s", phone_number[:6] + "****", exc)
    finally:
        db.close()


@router.post("/whatsapp/webhook", status_code=status.HTTP_200_OK)
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
        messages = value.get("messages") or []
        if not messages:
            return {"ok": True}

        msg = messages[0]
        msg_type = msg.get("type", "")
        phone_number = msg.get("from", "")
        msg_id = msg.get("id", "")
        msg_timestamp = msg.get("timestamp", "0")

        if not phone_number:
            return {"ok": True}

        if msg_id and _is_duplicate_or_stale(msg_id, msg_timestamp):
            return {"ok": True}

        if msg_type == "text":
            user_text = (msg.get("text") or {}).get("body", "").strip()
            if not user_text:
                return {"ok": True}
        elif msg_type == "interactive":
            interactive = msg.get("interactive") or {}
            itype = interactive.get("type", "")
            if itype == "button_reply":
                bid = (interactive.get("button_reply") or {}).get("id", "")
            elif itype == "list_reply":
                bid = (interactive.get("list_reply") or {}).get("id", "")
            else:
                return {"ok": True}
            user_text = _INTERACTIVE_CMD_MAP.get(bid, "help")
        elif msg_type in ("image", "document", "audio", "video"):
            background_tasks.add_task(_process_media_upload, phone_number)
            return {"ok": True}
        else:
            return {"ok": True}

        background_tasks.add_task(_process_whatsapp_message, phone_number, user_text)

    except Exception as exc:
        log.exception("WhatsApp webhook parse error | %s", exc)

    return {"ok": True}


@router.get("/wa/auth/{token}")
async def whatsapp_magic_auth(token: str, response: Response, db: Session = Depends(get_db)):
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
    redirect = record.redirect_to if _is_safe_redirect(record.redirect_to) else "/profile"
    log.info("WhatsApp magic auth success | phone=%s | redirect=%s", record.phone_number[:6] + "****", redirect)
    metrics.increment("whatsapp_magic_logins")
    return {"ok": True, "redirect": redirect}
