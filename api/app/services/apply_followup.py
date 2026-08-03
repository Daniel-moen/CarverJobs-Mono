"""
Next-day "did you apply?" follow-up — the second half of the match-feedback loop.

A match run only proves value if crew actually apply, and "did you get the
job?" is the future hire-attribution hook. This sweep finds users whose latest
match run completed a while ago (default 18h), who are still inside Meta's
24-hour free-form service window (last inbound < 23h ago — no template cost),
and asks once per run whether they applied. Replies route through the normal
webhook handlers (btn_applied_yes / btn_applied_notyet / btn_applied_none) and
"applied N" logs a per-job `applied` row in match_interactions.

Free-form interactive messages outside the service window are rejected by Meta,
so the window check is a hard gate, not an optimisation.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from app import flags
from app.analytics import record_server_event
from app.logger import get_logger
from app.models import MatchSession, WhatsAppSession
from app.services.proactive import SERVICE_WINDOW_HOURS, as_aware as _as_aware, recently_pinged
from app.settings import settings

log = get_logger("carver.apply_followup")

# Don't ask about runs so old the user has surely moved on.
_MAX_RUN_AGE_DAYS = 7
# Safety cap per sweep while Meta messaging limits are still low.
_MAX_SENDS_PER_RUN = 50


async def run_apply_followups_once() -> dict[str, int]:
    """One follow-up sweep. Returns counts for logging/tests."""
    from app.database import SessionLocal
    from app.routes.whatsapp import _send_whatsapp_buttons, _wa_configured

    stats = {"checked": 0, "sent": 0, "outside_window": 0, "already_asked": 0}
    if not _wa_configured():
        return stats
    if not flags.is_enabled("whatsapp"):
        return stats

    now = datetime.now(timezone.utc)
    min_age = timedelta(hours=settings.APPLY_FOLLOWUP_MIN_AGE_HOURS)
    window_floor = now - timedelta(hours=SERVICE_WINDOW_HOURS)

    db = SessionLocal()
    try:
        sessions = (
            db.query(WhatsAppSession)
            .filter(
                WhatsAppSession.mode == "chat",
                WhatsAppSession.last_match_session_id.isnot(None),
            )
            .all()
        )
        for ws in sessions:
            if stats["sent"] >= _MAX_SENDS_PER_RUN:
                log.warning("Apply follow-ups: per-run cap (%d) reached", _MAX_SENDS_PER_RUN)
                break
            stats["checked"] += 1

            ms = db.query(MatchSession).filter(MatchSession.id == ws.last_match_session_id).first()
            if ms is None or (ms.total_matched or 0) <= 0:
                continue
            completed = _as_aware(ms.completed_at) or _as_aware(ms.created_at)
            if completed is None or now - completed < min_age:
                continue
            if now - completed > timedelta(days=_MAX_RUN_AGE_DAYS):
                continue

            asked = _as_aware(ws.last_apply_followup_at)
            if asked is not None and asked > completed:
                stats["already_asked"] += 1
                continue

            last_active = _as_aware(ws.last_active_at)
            if last_active is None or last_active < window_floor:
                stats["outside_window"] += 1
                continue

            # Another proactive loop may have just messaged them.
            if recently_pinged(ws, now):
                stats["already_asked"] += 1
                continue

            await _send_whatsapp_buttons(
                ws.phone_number,
                "Quick check-in 👋 Did you get an application in for any of your recent matches?",
                [
                    ("btn_applied_yes", "✅ Yes, applied"),
                    ("btn_applied_notyet", "⏳ Not yet"),
                    ("btn_applied_none", "🤷 None fit me"),
                ],
            )
            ws.last_apply_followup_at = now
            db.commit()
            stats["sent"] += 1
            record_server_event(ws.phone_number, "apply_followup_sent", str(ms.id))
    finally:
        db.close()

    if stats["sent"]:
        log.info(
            "Apply follow-up sweep done | checked=%d | sent=%d | outside_window=%d | already_asked=%d",
            stats["checked"], stats["sent"], stats["outside_window"], stats["already_asked"],
        )
    return stats


async def apply_followup_loop() -> None:
    """Background asyncio task started at API startup."""
    interval_seconds = settings.APPLY_FOLLOWUP_CHECK_INTERVAL_HOURS * 60 * 60
    # Let DB init settle before the first sweep.
    await asyncio.sleep(420)
    while True:
        try:
            await run_apply_followups_once()
        except Exception as exc:
            log.error("Apply follow-up sweep failed | error=%s", exc)
        await asyncio.sleep(interval_seconds)
