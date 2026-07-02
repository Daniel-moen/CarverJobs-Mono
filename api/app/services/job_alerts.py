"""
Proactive WhatsApp job alerts — the retention loop.

Matching is episodic and user-initiated, so nothing brings crew back between
job hunts. This loop closes that gap: it periodically checks each onboarded
WhatsApp user for newly ingested jobs that plausibly fit their desired role and
sends a pre-approved Meta *template* message ("Hi {{1}}, {{2}} new jobs match
your profile — reply *match* to see them").

Business-initiated messages outside the 24h service window REQUIRE an approved
template (paid per message), so this whole feature is OFF until
WHATSAPP_JOB_ALERT_TEMPLATE is configured with the approved template name.
The template must take two body params: {{1}} = first name, {{2}} = job count.

Role matching here is deliberately cheap (substring on role/title) — the alert
only claims jobs *might* fit; the real AI matching runs when the user replies
*match*. No LLM spend on alerts.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from app import flags
from app.analytics import record_server_event
from app.logger import get_logger
from app.models import CrewProfile, Job, WhatsAppSession
from app.settings import settings

log = get_logger("carver.job_alerts")

_GRAPH_URL = "https://graph.facebook.com/v19.0"
_ACTIVE_STATUSES = ("open", "priority")
# Never alert about jobs older than this, even for long-dormant users.
_MAX_JOB_AGE_DAYS = 7
# Safety cap per cycle while Meta messaging limits are still low.
_MAX_ALERTS_PER_RUN = 50


def _configured() -> bool:
    return bool(
        settings.WHATSAPP_JOB_ALERT_TEMPLATE
        and settings.WHATSAPP_PHONE_NUMBER_ID
        and settings.WHATSAPP_ACCESS_TOKEN
    )


def _role_tokens(desired_role: str) -> list[str]:
    """Split "Deckhand, Engineer / ETO" into lowercase match tokens."""
    raw = desired_role.replace("/", ",").replace("&", ",")
    return [t.strip().lower() for t in raw.split(",") if len(t.strip()) >= 3]


def _matching_jobs(jobs: list[Job], desired_role: str) -> list[Job]:
    tokens = _role_tokens(desired_role or "")
    if not tokens:
        return []
    out = []
    for job in jobs:
        haystack = f"{job.role or ''} {job.title or ''}".lower()
        if any(t in haystack for t in tokens):
            out.append(job)
    return out


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


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


async def run_job_alerts_once() -> dict[str, int]:
    """One alert sweep. Returns counts for logging/tests."""
    from app.database import SessionLocal

    stats = {"checked": 0, "sent": 0, "skipped_recent": 0, "no_match": 0}
    if not _configured():
        log.debug("Job alerts not configured (WHATSAPP_JOB_ALERT_TEMPLATE unset) — skipping")
        return stats
    if not flags.is_enabled("whatsapp"):
        log.info("Job alerts skipped — whatsapp feature flag disabled")
        return stats

    now = datetime.now(timezone.utc)
    min_interval = timedelta(hours=settings.JOB_ALERT_MIN_INTERVAL_HOURS)
    freshness_floor = now - timedelta(days=_MAX_JOB_AGE_DAYS)

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

                ok = await _send_template(client, ws.phone_number, profile.first_name or "", len(matches))
                if ok:
                    ws.last_job_alert_at = now
                    db.commit()
                    stats["sent"] += 1
                    record_server_event(ws.phone_number, "job_alert_sent", str(len(matches)))
    finally:
        db.close()

    log.info(
        "Job alert sweep done | checked=%d | sent=%d | skipped_recent=%d | no_match=%d",
        stats["checked"], stats["sent"], stats["skipped_recent"], stats["no_match"],
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
