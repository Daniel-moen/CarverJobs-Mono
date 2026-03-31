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
from app.models import CrewProfile, Document, Job, JobHistoryEntry, WhatsAppMagicToken, WhatsAppSession
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
    "btn_apply_1": "apply 1",
    "btn_apply_2": "apply 2",
    "btn_apply_3": "apply 3",
    "btn_job_info_1": "job_info 1",
    "btn_job_info_2": "job_info 2",
    "btn_job_info_3": "job_info 3",
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


def _make_magic_link(phone_number: str, db: Session, *, redirect_to: str | None = None) -> str:
    """Create a WhatsAppMagicToken and return the full magic link URL.

    ``redirect_to`` must be a known internal path (validated against an allowlist
    to prevent open-redirect attacks).  Defaults to ``/profile`` when omitted.
    """
    safe_redirect = redirect_to if redirect_to in _ALLOWED_REDIRECTS else None
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


async def _call_openai(system: str, history: list, user_message: str) -> dict:
    """Call OpenAI and return parsed JSON dict."""
    messages = [{"role": "system", "content": system}]
    for msg in history[-16:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message or "Begin."})

    resp = await _http.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
        json={
            "model": settings.OPENAI_MODEL,
            "messages": messages,
            "temperature": 0.5,
            "max_tokens": 500,
            "response_format": {"type": "json_object"},
        },
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
    """Run the AI matching engine and send results with apply buttons.

    Uses the same matching_engine as the website — one engine, consistent results.
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
            "🙈 *No Crew Profile*\n\nSet up your profile first so we can match you to superyacht roles. Tap below — quick setup!",
        )
        await _send_whatsapp_buttons(
            phone_number,
            "Ready to join the fleet?",
            [("btn_edit_profile", "Edit Profile"), ("btn_help", "Help")],
        )
        return

    if not settings.OPENAI_API_KEY:
        await _send_whatsapp(phone_number, "⚠️ Matching engine is in dry dock. Please try again soon.")
        return

    all_jobs = (
        db.query(Job)
        .filter(Job.status.in_(["open", "priority"]))
        .order_by(Job.created_at.desc())
        .all()
    )
    if not all_jobs:
        await _send_whatsapp(
            phone_number,
            "📭 *No Open Yacht Roles Right Now*\n\nNo positions at the moment. New crew roles drop regularly — check back soon!",
        )
        return

    _BATCH_SIZE = 10
    _AVG_SECS_PER_BATCH = 8
    num_batches = _math.ceil(len(all_jobs) / _BATCH_SIZE)
    est_secs = num_batches * _AVG_SECS_PER_BATCH
    est_str = f"~{est_secs} seconds" if est_secs < 60 else f"~{round(est_secs / 60)} min"

    await _send_whatsapp(
        phone_number,
        f"⏳ *Finding Your Matches...*\n\n"
        f"Scanning *{len(all_jobs)} yacht positions* — estimated time: *{est_str}*.\n\n"
        f"Stand by, we'll send your results shortly!",
    )

    # Build candidate profile (same as website)
    certs = [c.strip() for c in (profile.certifications or "").replace("\n", ",").split(",") if c.strip()]
    langs = [lang.strip() for lang in (profile.languages or "").split(",") if lang.strip()]

    job_history_entries = (
        db.query(JobHistoryEntry)
        .filter(JobHistoryEntry.user_key == phone_number)
        .order_by(JobHistoryEntry.start_date.desc())
        .limit(10)
        .all()
    )
    history = [
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
        job_history=history,
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
        await _send_whatsapp(phone_number, "⚠️ Matching hit a snag. Give it another try in a moment.")
        return

    # Return ALL matches (matched=True) — no extra compatibility filter
    matched = [r for r in (results or []) if r.matched]
    if not matched:
        await _send_whatsapp(
            phone_number,
            "😔 *No Strong Matches Yet*\n\nNo great yacht fit right now. A complete crew profile with certs and docs boosts your chances — keep it shipshape!",
        )
        await _send_whatsapp_buttons(
            phone_number,
            "Want to improve your match rate?",
            [("btn_edit_profile", "Edit Profile"), ("btn_upload_docs", "Upload Docs"), ("btn_menu", "Main Menu")],
        )
        return

    # WhatsApp buttons only support 3 — store top 3 for interactive actions, list rest as text
    top_matches = matched[:3]
    stored = []
    for m in top_matches:
        job = jobs_by_id.get(m.job_id)
        if not job:
            continue
        stored.append({"job_id": job.id, "title": job.title, "contact_email": job.contact_email or ""})

    partial = json.loads(wa_session.partial_profile)
    partial["_last_matches"] = stored
    _save_session(wa_session, db, json.loads(wa_session.history), partial)
    metrics.increment("crew_matches")

    await _send_whatsapp(
        phone_number,
        f"🎯 *Found {len(matched)} yacht match{'es' if len(matched) != 1 else ''}!*\n\n"
        f"Showing your top matches — tap *See More* for details or *Draft Application* to apply.",
    )

    # Button messages for top 3
    num_labels = ["1️⃣", "2️⃣", "3️⃣"]
    for i, m in enumerate(top_matches, 1):
        job = jobs_by_id.get(m.job_id)
        if not job:
            continue
        compat = int(m.compatibility)
        salary_line = ""
        if job.salary_min or job.salary_max:
            lo = f"€{int(job.salary_min)}" if job.salary_min else ""
            hi = f"€{int(job.salary_max)}" if job.salary_max else ""
            salary_str = f"{lo}–{hi}/mo" if lo and hi else f"{lo or hi}/mo"
            salary_line = f"\n💰 {salary_str}"
        reason = f"\n_\"{m.reason[:120]}\"_" if m.reason else ""
        body = (
            f"{num_labels[i - 1]} *{job.title}*\n"
            f"📍 {job.location}  ·  ✅ {compat}% match"
            f"{salary_line}{reason}"
        )
        await _send_whatsapp_buttons(
            phone_number,
            body,
            [
                (f"btn_job_info_{i}", "See More"),
                (f"btn_apply_{i}", "Draft Application"),
            ],
        )

    # List remaining matches as text (if more than 3)
    if len(matched) > 3:
        extra_lines = []
        for m in matched[3:]:
            job = jobs_by_id.get(m.job_id)
            if not job:
                continue
            compat = int(m.compatibility)
            extra_lines.append(f"• *{job.title}* — {job.location} ({compat}%)")
        if extra_lines:
            await _send_whatsapp(
                phone_number,
                f"📋 *{len(extra_lines)} more match{'es' if len(extra_lines) != 1 else ''}:*\n\n"
                + "\n".join(extra_lines)
                + "\n\n_Check the job board for full details on all positions._",
            )


async def _handle_job_info_command(number: int, wa_session: WhatsAppSession, db: Session) -> None:
    """Send full details for a stored match result."""
    phone = wa_session.phone_number
    partial = json.loads(wa_session.partial_profile)
    last_matches = partial.get("_last_matches", [])

    if not last_matches or number > len(last_matches):
        await _send_whatsapp(phone, "🔍 *No Recent Matches*\n\nRun *Find Matches* first to scan yacht positions.")
        return

    match_data = last_matches[number - 1]
    job = db.query(Job).filter(Job.id == match_data["job_id"]).first()
    if not job:
        await _send_whatsapp(phone, "😔 That yacht role is no longer available.")
        return

    num_labels = ["1️⃣", "2️⃣", "3️⃣"]
    lines = [f"{num_labels[number - 1]} *{job.title}*\n"]

    if job.role:          lines.append(f"⚓ *Role:* {job.role}")
    if job.location:      lines.append(f"📍 *Location:* {job.location}")
    if job.yacht:         lines.append(f"🛥️ *Yacht:* {job.yacht}")
    if job.contract_type: lines.append(f"📋 *Contract:* {job.contract_type}")
    if job.start_date:    lines.append(f"📅 *Start date:* {job.start_date}")
    if job.salary_min or job.salary_max:
        lo = f"€{int(job.salary_min)}" if job.salary_min else ""
        hi = f"€{int(job.salary_max)}" if job.salary_max else ""
        salary_str = f"{lo}–{hi}/mo" if lo and hi else f"{lo or hi}/mo"
        lines.append(f"💰 *Salary:* {salary_str}")
    if job.certifications_required:
        lines.append(f"🏅 *Certs required:* {job.certifications_required}")
    if job.description:
        lines.append(f"\n📝 *About the role:*\n{job.description[:700]}")
    if job.requirements:
        lines.append(f"\n✅ *Requirements:*\n{job.requirements[:400]}")
    if job.contact_email:
        lines.append(f"\n📧 *Contact:* {job.contact_email}")

    await _send_whatsapp(phone, "\n".join(lines))
    await _send_whatsapp_buttons(
        phone,
        "Ready to apply for this yacht role?",
        [
            (f"btn_apply_{number}", "Draft Application"),
            ("btn_find_matches", "Find More Jobs"),
            ("btn_menu", "Main Menu"),
        ],
    )


async def _handle_apply_command(number: int, wa_session: WhatsAppSession, db: Session) -> None:
    """Draft an application email for a stored match result, sending messages directly."""
    import asyncio
    from urllib.parse import quote as _quote
    from app.services.ai_client import call_openai

    phone = wa_session.phone_number
    partial = json.loads(wa_session.partial_profile)
    last_matches = partial.get("_last_matches", [])

    if not last_matches:
        await _send_whatsapp(phone, "🔍 *No Recent Matches*\n\nRun *Find Matches* first to find yacht roles, then tap one to apply.")
        return

    idx = number - 1
    if idx < 0 or idx >= len(last_matches):
        await _send_whatsapp(phone, f"⚠️ Please choose a number between 1 and {len(last_matches)}.")
        return

    match_data = last_matches[idx]
    job = db.query(Job).filter(Job.id == match_data["job_id"]).first()
    if not job:
        await _send_whatsapp(phone, "😔 That yacht role is no longer available.")
        return

    profile = db.query(CrewProfile).filter(CrewProfile.user_key == phone).first()
    if not profile:
        await _send_whatsapp(phone, "🙈 *No Crew Profile*\n\nSet up your profile before applying to yacht roles. Tap *Edit Profile* to get started.")
        return

    if not settings.OPENAI_API_KEY:
        await _send_whatsapp(phone, "⚠️ Email drafting is in dry dock. Try again in a moment.")
        return

    name = " ".join(filter(None, [profile.first_name, profile.last_name])) or "the applicant"
    first_name = (profile.first_name or name.split()[0])
    profile_url = f"{settings.FRONTEND_BASE_URL}/crew/{profile.profile_slug}" if profile.profile_slug else ""

    # Build a rich candidate summary for the AI
    profile_parts = []
    if profile.desired_role:       profile_parts.append(f"Desired role: {profile.desired_role}")
    if profile.years_experience:   profile_parts.append(f"Years experience: {profile.years_experience}")
    if profile.nationality:        profile_parts.append(f"Nationality: {profile.nationality}")
    if profile.current_location:   profile_parts.append(f"Current location: {profile.current_location}")
    if profile.preferred_locations:profile_parts.append(f"Preferred locations: {profile.preferred_locations}")
    if profile.contract_type:      profile_parts.append(f"Contract preference: {profile.contract_type}")
    if profile.certifications:     profile_parts.append(f"Certifications: {profile.certifications}")
    if profile.languages:          profile_parts.append(f"Languages: {profile.languages}")
    if profile.salary_min or profile.salary_max:
        profile_parts.append(f"Salary expectation: €{profile.salary_min or '?'}–€{profile.salary_max or '?'}/mo")
    if profile.available_from:     profile_parts.append(f"Available from: {profile.available_from}")
    if profile.bio:                profile_parts.append(f"Bio: {profile.bio[:300]}")
    candidate_summary = "\n".join(profile_parts)

    system_prompt = f"""You are writing a genuine, personal job application email on behalf of {name}, a superyacht crew member.

Your task: write a compelling, specific email that feels like a real human wrote it — not a template.
- Open with something specific to the role or yacht if possible (e.g. mention the yacht name, the location, the contract type)
- Highlight the 1–2 most relevant qualifications from the candidate's profile that directly match what this job needs
- Keep it concise — under 150 words — but make every sentence count
- Sound confident and enthusiastic, not desperate or generic
- Do NOT use phrases like "I am writing to express my interest" — start with something more direct
- Do NOT include a profile link — it will be appended automatically
- Close with the candidate's first name only ({first_name})

Candidate profile:
{candidate_summary}

Job being applied for:
Title: {job.title}
Role: {job.role}
Yacht: {job.yacht or 'not specified'}
Location: {job.location}
Contract: {job.contract_type or 'not specified'}
Description: {(job.description or '')[:500]}
Requirements: {(job.requirements or '')[:400]}

Return strict JSON only — no markdown:
{{"subject": "<punchy subject line — include role and yacht name>", "body": "<the full email body text>"}}"""

    try:
        text = await asyncio.to_thread(
            call_openai,
            api_key=settings.OPENAI_API_KEY,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Draft the application email."},
            ],
            model=settings.OPENAI_MODEL,
            max_tokens=400,
            temperature=0.7,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        log.error("WhatsApp apply email draft failed | %s", exc)
        await _send_whatsapp(phone, "⚠️ Couldn't draft the email. Give it another try in a moment.")
        return

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        await _send_whatsapp(phone, "⚠️ Couldn't parse the draft. Please try again.")
        return

    subject = parsed.get("subject", f"Application: {job.role} – {job.yacht}")
    body = parsed.get("body", "")

    # Always append the CARVER profile link so recruiters can view the full profile
    if profile_url:
        body = f"{body}\n\nView my full crew profile: {profile_url}"

    to_email = job.contact_email or ""
    metrics.increment("whatsapp_apply_drafts")

    if to_email:
        mailto = (
            f"mailto:{_quote(to_email)}"
            f"?subject={_quote(subject)}"
            f"&body={_quote(body)}"
        )
        send_action = f"👉 *Open in email app:*\n{mailto}"
    else:
        send_action = "_(no contact email on file — check the job board)_"

    # ── Message 1: header card (no body) ──
    await _send_whatsapp(
        phone,
        f"✉️ *Application Draft*\n"
        f"_{job.title}_\n\n"
        f"📧 *To:* {to_email or 'unknown'}\n"
        f"📝 *Subject:* {subject}\n\n"
        f"{send_action}",
    )

    # ── Message 2: clean body — long-press → Copy in WhatsApp ──
    await _send_whatsapp(
        phone,
        f"📋 *Long-press to copy:*\n\n{body}",
    )


# ── Onboarding flow ───────────────────────────────────────────────────────────

_FIRST_ONBOARD_MESSAGE = (
    "Ahoy! 👋 Welcome aboard CARVER — your superyacht crew platform. "
    "Let's build your crew profile in a few quick questions. What's your full name?"
)


async def _run_onboarding(wa_session: WhatsAppSession, user_message: str, db: Session) -> str:
    history = json.loads(wa_session.history)
    partial = json.loads(wa_session.partial_profile)

    # First message: use fixed welcome to avoid odd AI phrasing like "trouble connecting"
    if not history:
        message = _FIRST_ONBOARD_MESSAGE
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": message})
        _save_session(wa_session, db, history, partial)
        return message

    system = _build_onboard_system(partial)
    parsed = await _call_openai(system, history, user_message)

    message = (parsed.get("message") or "").strip()
    done = bool(parsed.get("done"))
    updates = parsed.get("updates") if isinstance(parsed.get("updates"), dict) else {}
    clean_updates = {k: str(v).strip() for k, v in updates.items() if isinstance(k, str) and v and str(v).strip()}

    partial = _apply_updates(partial, clean_updates)

    if not message:
        missing = [f for f in REQUIRED_ONBOARD_FIELDS if not str(partial.get(f, "")).strip()]
        if missing:
            question = _FIELD_QUESTIONS.get(missing[0], f"Could you tell me your {_FIELD_LABELS.get(missing[0], missing[0])}?")
            message = f"Got it! {question}"
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

    import re as _re

    # job_info 1 / job_info 2 / job_info 3
    job_info_match = _re.match(r'^job_info\s+([123])$', cmd)
    if job_info_match:
        await _handle_job_info_command(int(job_info_match.group(1)), wa_session, db)
        return None

    # apply 1 / apply 2 / apply 3
    apply_match = _re.match(r'^apply\s+([123])$', cmd)
    if apply_match:
        await _handle_apply_command(int(apply_match.group(1)), wa_session, db)
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
    """Validate a WhatsApp magic link token and issue a session cookie."""
    if len(token) > 64:
        raise HTTPException(status_code=400, detail="Invalid token")

    record = db.query(WhatsAppMagicToken).filter(WhatsAppMagicToken.token == token).first()
    if not record:
        raise HTTPException(status_code=404, detail="Link not found or already used")
    if record.used:
        raise HTTPException(status_code=410, detail="This link has already been used")
    now = datetime.now(timezone.utc)
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if now > expires:
        raise HTTPException(status_code=410, detail="This link has expired. Type 'edit' on WhatsApp to get a new one.")

    record.used = True
    db.commit()

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
    redirect = record.redirect_to if record.redirect_to in _ALLOWED_REDIRECTS else "/profile"
    log.info("WhatsApp magic auth success | phone=%s | redirect=%s", record.phone_number[:6] + "****", redirect)
    metrics.increment("whatsapp_magic_logins")
    return {"ok": True, "redirect": redirect}
