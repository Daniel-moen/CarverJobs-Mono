"""
Proactive WhatsApp job alerts — the retention loop.

Matching is episodic and user-initiated, so nothing brings crew back between
job hunts. This loop closes that gap: it periodically checks each onboarded
WhatsApp user for newly ingested jobs that plausibly fit their desired role and
tells them about it.

Two send channels, picked per user:

* **Free-form** (preferred) — if the user messaged us within Meta's 24h service
  window, a normal interactive message is allowed and costs R0. It can name the
  actual jobs, which converts better than a bare count, and it needs no
  template approval, so this half of the loop works today.
* **Template** — outside that window Meta only accepts a pre-approved template
  (paid per message). That half stays dormant until
  WHATSAPP_JOB_ALERT_TEMPLATE is set to the approved template name; the
  template must take two body params: {{1}} = first name, {{2}} = job count.

So the loop runs as soon as WhatsApp credentials exist, reaching recently
active users for free, and automatically widens to dormant users the moment the
template lands — no code change at that point, just the env var.

Role matching here is deliberately cheap (deterministic role taxonomy, no AI)
— the alert only claims jobs *might* fit; the real AI matching runs when the
user replies *match*. No LLM spend on alerts.
"""
import asyncio
import re
from datetime import datetime, timedelta, timezone

import httpx

from app import flags
from app.analytics import record_server_event
from app.logger import get_logger
from app.models import CrewProfile, Job, WhatsAppSession
from app.services.proactive import (
    SERVICE_WINDOW_HOURS,
    as_aware as _as_aware,
    recently_pinged,
)
from app.services.role_taxonomy import (
    RELATED_ADJACENT,
    normalize_role,
    normalize_roles,
    roles_related,
)
from app.settings import settings

log = get_logger("carver.job_alerts")

_GRAPH_URL = "https://graph.facebook.com/v19.0"
_ACTIVE_STATUSES = ("open", "priority")
# Never alert about jobs older than this, even for long-dormant users.
_MAX_JOB_AGE_DAYS = 7
# Safety cap per cycle while Meta messaging limits are still low.
_MAX_ALERTS_PER_RUN = 50
# How many job titles to name in a free-form alert before summarising the rest.
_FREEFORM_JOB_PREVIEW = 3


def _wa_credentials_ok() -> bool:
    return bool(settings.WHATSAPP_PHONE_NUMBER_ID and settings.WHATSAPP_ACCESS_TOKEN)


def _template_configured() -> bool:
    return bool(settings.WHATSAPP_JOB_ALERT_TEMPLATE)


# A job counts as a match when it is the same role or an adjacent one in the
# same department (deckhand <-> bosun, stew <-> chief stew).
_ALERT_RELATEDNESS_MIN = RELATED_ADJACENT


def _role_tokens(desired_role: str) -> list[str]:
    """Normalise "Deckhand, Engineer / ETO" into canonical role tokens.

    Uses the curated role taxonomy so abbreviations resolve sensibly ("stew" ->
    stewardess, "eng" -> engineer). Parts the taxonomy doesn't know fall back
    to plain lowercase tokens (min 4 chars, so short fragments can't
    substring-match half the job board).
    """
    tokens: list[str] = []
    raw = desired_role.replace("/", ",").replace("&", ",")
    for part in raw.split(","):
        part = part.strip().lower()
        if not part:
            continue
        token = normalize_role(part) or (part if len(part) >= 4 else "")
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _matching_jobs(jobs: list[Job], desired_role: str) -> list[Job]:
    desired = (desired_role or "").strip()
    if not desired:
        return []
    known_roles = normalize_roles(desired)
    fallback_tokens = [t for t in _role_tokens(desired) if t not in known_roles]
    if not known_roles and not fallback_tokens:
        return []
    fallback_patterns = [
        re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])")
        for t in fallback_tokens
    ]
    out = []
    for job in jobs:
        haystack = f"{job.role or ''} {job.title or ''}"
        if known_roles and roles_related(desired, haystack) >= _ALERT_RELATEDNESS_MIN:
            out.append(job)
            continue
        hs = haystack.lower()
        if any(p.search(hs) for p in fallback_patterns):
            out.append(job)
    return out


async def _send_template(client: httpx.AsyncClient, phone: str, first_name: str, count: int) -> bool:
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": settings.WHATSAPP_JOB_ALERT_TEMPLATE,
            "language": {"code": settings.WHATSAPP_JOB_ALERT_LANGUAGE},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": first_name or "there"},
                    {"type": "text", "text": str(count)},
                ],
            }],
        },
    }
    try:
        resp = await client.post(
            f"{_GRAPH_URL}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages",
            json=payload,
            headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"},
            timeout=20.0,
        )
        if resp.status_code >= 400:
            log.error("Job alert template send failed | to=%s | status=%d | body=%s",
                      phone[:6] + "****", resp.status_code, resp.text[:300])
            return False
        return True
    except httpx.HTTPError as exc:
        log.error("Job alert template send error | to=%s | %s", phone[:6] + "****", exc)
        return False


def _freeform_body(first_name: str, jobs: list[Job]) -> str:
    """Alert copy for the free-form channel — names real jobs, not just a count.

    The template channel is stuck with "{{2}} new jobs"; inside the service
    window we can show what actually landed, which is the whole reason this
    channel converts better.
    """
    who = (first_name or "").strip() or "there"
    count = len(jobs)
    lines = [
        f"Hi {who} 👋 {count} new job{'s' if count != 1 else ''} landed that look like your kind of role:",
        "",
    ]
    for job in jobs[:_FREEFORM_JOB_PREVIEW]:
        title = (job.title or job.role or "New role").strip()
        where = (job.location or "").strip()
        lines.append(f"• {title}{f' — {where}' if where else ''}")
    remaining = count - min(count, _FREEFORM_JOB_PREVIEW)
    if remaining > 0:
        lines.append(f"• …and {remaining} more")
    lines += ["", "Want me to check them against your profile?"]
    return "\n".join(lines)


async def _send_freeform(phone: str, first_name: str, jobs: list[Job]) -> bool:
    """Interactive alert inside the 24h service window. Costs nothing to send."""
    from app.routes.whatsapp import _send_whatsapp_buttons

    try:
        await _send_whatsapp_buttons(
            phone,
            _freeform_body(first_name, jobs),
            [
                ("btn_match_recent", "🔍 Show me"),
                ("btn_view_profile", "👤 My profile"),
            ],
        )
        return True
    except Exception as exc:  # send helpers swallow HTTP errors; guard the rest
        log.error("Job alert free-form send failed | to=%s | %s", phone[:6] + "****", exc)
        return False


async def run_job_alerts_once() -> dict[str, int]:
    """One alert sweep. Returns counts for logging/tests."""
    from app.database import SessionLocal

    stats = {
        "checked": 0, "sent": 0, "sent_freeform": 0, "sent_template": 0,
        "skipped_recent": 0, "no_match": 0, "needs_template": 0,
    }
    if not _wa_credentials_ok():
        log.debug("Job alerts skipped — WhatsApp credentials not configured")
        return stats
    if not flags.is_enabled("whatsapp"):
        log.info("Job alerts skipped — whatsapp feature flag disabled")
        return stats

    now = datetime.now(timezone.utc)
    min_interval = timedelta(hours=settings.JOB_ALERT_MIN_INTERVAL_HOURS)
    freshness_floor = now - timedelta(days=_MAX_JOB_AGE_DAYS)
    window_floor = now - timedelta(hours=SERVICE_WINDOW_HOURS)

    db = SessionLocal()
    try:
        recent_jobs = (
            db.query(Job)
            .filter(Job.status.in_(_ACTIVE_STATUSES), Job.created_at >= freshness_floor)
            .all()
        )
        if not recent_jobs:
            log.info("Job alerts: no fresh jobs in the last %dd — nothing to send", _MAX_JOB_AGE_DAYS)
            return stats

        sessions = (
            db.query(WhatsAppSession)
            .filter(WhatsAppSession.mode == "chat")
            .all()
        )

        async with httpx.AsyncClient() as client:
            for ws in sessions:
                if stats["sent"] >= _MAX_ALERTS_PER_RUN:
                    log.warning("Job alerts: per-run cap (%d) reached", _MAX_ALERTS_PER_RUN)
                    break
                stats["checked"] += 1

                last_alert = _as_aware(ws.last_job_alert_at)
                if last_alert and now - last_alert < min_interval:
                    stats["skipped_recent"] += 1
                    continue

                # Never land an alert right after another loop's message —
                # two proactive pings in an afternoon reads as spam.
                if recently_pinged(ws, now):
                    stats["skipped_recent"] += 1
                    continue

                profile = (
                    db.query(CrewProfile)
                    .filter(CrewProfile.user_key == ws.phone_number)
                    .first()
                )
                if not profile or not (profile.desired_role or "").strip():
                    continue

                # Only jobs the user hasn't been alerted about yet.
                baseline = last_alert or _as_aware(ws.created_at) or freshness_floor
                new_jobs = [j for j in recent_jobs if (_as_aware(j.created_at) or now) > baseline]
                matches = _matching_jobs(new_jobs, profile.desired_role)
                if not matches:
                    stats["no_match"] += 1
                    continue

                # Inside the service window a free-form send is allowed and free;
                # outside it Meta accepts nothing but an approved template.
                last_active = _as_aware(ws.last_active_at)
                in_window = last_active is not None and last_active >= window_floor
                if in_window:
                    channel = "freeform"
                    ok = await _send_freeform(ws.phone_number, profile.first_name or "", matches)
                elif _template_configured():
                    channel = "template"
                    ok = await _send_template(
                        client, ws.phone_number, profile.first_name or "", len(matches)
                    )
                else:
                    stats["needs_template"] += 1
                    continue

                if ok:
                    ws.last_job_alert_at = now
                    db.commit()
                    stats["sent"] += 1
                    stats[f"sent_{channel}"] += 1
                    record_server_event(
                        ws.phone_number, "job_alert_sent", f"{channel}:{len(matches)}"
                    )
    finally:
        db.close()

    log.info(
        "Job alert sweep done | checked=%d | sent=%d (freeform=%d template=%d) | "
        "skipped_recent=%d | no_match=%d | needs_template=%d",
        stats["checked"], stats["sent"], stats["sent_freeform"], stats["sent_template"],
        stats["skipped_recent"], stats["no_match"], stats["needs_template"],
    )
    if stats["needs_template"] and not _template_configured():
        log.info(
            "Job alerts: %d dormant user(s) matched but are outside the 24h window — "
            "set WHATSAPP_JOB_ALERT_TEMPLATE to reach them",
            stats["needs_template"],
        )
    return stats


async def job_alert_loop() -> None:
    """Background asyncio task started at API startup. No-ops until configured."""
    interval_seconds = settings.JOB_ALERT_CHECK_INTERVAL_HOURS * 60 * 60
    # Let DB init and the first scrape settle before the first sweep.
    await asyncio.sleep(300)
    while True:
        try:
            await run_job_alerts_once()
        except Exception as exc:
            log.error("Job alert sweep failed | error=%s", exc)
        await asyncio.sleep(interval_seconds)
