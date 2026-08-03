"""Win-back nudges for users no other proactive loop can see.

The other two loops both assume a completed match run: the quality pulse fires
10 min after results land, and the "did you apply?" sweep requires
``total_matched > 0``. That leaves the two groups who leak worst with nothing:

* users who stopped part-way through onboarding (they never reach ``chat`` mode,
  so every other sweep filters them out); and
* users who finished onboarding but have no match run to follow up on.

Both go quiet, their Meta service window expires unnoticed, and from then on they
can only be reached with a paid template — which may be days from approval, by
which point the intent that brought them in is gone.

Two stages, both free-form and both inside the window, so neither needs a
template:

1. **Early** (default 3h after their last message, onboarding drop-outs only) —
   "did you want to finish?", while they still remember starting.
2. **Last chance** (default 20h, window closes at 23h) — the final moment a
   free-form message will still be delivered.

At most one nudge per stage per silent stretch. ``last_winback_at`` is compared
against ``last_active_at``, so replying re-arms both stages and ignoring them
does not.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from app import flags
from app.analytics import record_server_event
from app.logger import get_logger
from app.models import MatchSession, WhatsAppSession
from app.services.proactive import SERVICE_WINDOW_HOURS, as_aware, recently_pinged
from app.settings import settings

log = get_logger("carver.window_winback")

# Safety cap per sweep while Meta messaging limits are still low.
_MAX_SENDS_PER_RUN = 50


def _onboarding_progress(ws: WhatsAppSession) -> tuple[str, int]:
    """(first name, count of required fields still missing) from the partial profile."""
    from app.routes.whatsapp import REQUIRED_ONBOARD_FIELDS

    try:
        partial = json.loads(ws.partial_profile or "{}")
    except (ValueError, TypeError):
        partial = {}
    missing = [f for f in REQUIRED_ONBOARD_FIELDS if not str(partial.get(f, "")).strip()]
    return str(partial.get("firstName", "")).strip(), len(missing)


def _early_onboarding_nudge(ws: WhatsAppSession) -> tuple[str, list[tuple[str, str]]]:
    """Stage 1 — a few hours after they went quiet mid-onboarding."""
    name, missing = _onboarding_progress(ws)
    hello = f"Hey {name} 👋" if name else "Hey 👋"

    if missing <= 2:
        body = (
            f"{hello} You never finished setting up — you're {missing} "
            f"answer{'s' if missing != 1 else ''} away from your first job match. "
            "Want to wrap it up? Takes about 20 seconds."
        )
    else:
        body = (
            f"{hello} Did you want to finish setting up your profile? "
            "It's 4 quick questions and your first AI job match is free — "
            "just reply and we'll carry on where we stopped."
        )
    return body, []


def _last_chance_onboarding_nudge(ws: WhatsAppSession) -> tuple[str, list[tuple[str, str]]]:
    """Stage 2 — final free-form message before the window closes."""
    name, missing = _onboarding_progress(ws)
    hello = f"Hey {name}" if name else "Hey"
    return (
        f"{hello} — last nudge from me, promise 🙏 Your half-finished profile is "
        f"still here and you're {missing} answer{'s' if missing != 1 else ''} from "
        "seeing which live yacht jobs actually fit you. Reply any time and we'll "
        "pick it straight back up.",
        [],
    )


def _remember_assistant_turn(ws: WhatsAppSession, body: str) -> None:
    """Append the nudge to the stored chat history as an assistant turn."""
    try:
        history = json.loads(ws.history or "[]")
        if not isinstance(history, list):
            history = []
    except (ValueError, TypeError):
        history = []
    history.append({"role": "assistant", "content": body})
    ws.history = json.dumps(history)


def _no_match_nudge(_ws: WhatsAppSession) -> tuple[str, list[tuple[str, str]]]:
    """For someone who finished onboarding but never ran a match."""
    return (
        "Your profile's ready to go 🛥️ Want me to scan the live job board and "
        "rank what fits you? Takes about a minute — your first run is free.",
        [("btn_find_matches", "🔍 Find matches"), ("btn_view_profile", "👤 My profile")],
    )


async def run_window_winbacks_once() -> dict[str, int]:
    """One win-back sweep across both stages. Returns counts for logging/tests."""
    from app.database import SessionLocal
    from app.routes.whatsapp import _send_whatsapp, _send_whatsapp_buttons, _wa_configured

    stats = {
        "checked": 0, "sent": 0, "sent_early": 0, "sent_last_chance": 0,
        "too_early": 0, "window_closed": 0, "already_nudged": 0, "has_match_run": 0,
    }
    if not _wa_configured():
        return stats
    if not flags.is_enabled("whatsapp"):
        return stats

    now = datetime.now(timezone.utc)
    early_age = timedelta(hours=settings.WINDOW_WINBACK_EARLY_HOURS)
    last_chance_age = timedelta(hours=settings.WINDOW_WINBACK_MIN_AGE_HOURS)
    window_floor = now - timedelta(hours=SERVICE_WINDOW_HOURS)

    db = SessionLocal()
    try:
        sessions = (
            db.query(WhatsAppSession)
            .filter(WhatsAppSession.last_active_at.isnot(None))
            .all()
        )
        for ws in sessions:
            if stats["sent"] >= _MAX_SENDS_PER_RUN:
                log.warning("Window win-backs: per-run cap (%d) reached", _MAX_SENDS_PER_RUN)
                break
            stats["checked"] += 1

            last_active = as_aware(ws.last_active_at)
            if last_active is None:
                continue
            silent_for = now - last_active
            # Past the window nothing free-form is delivered, so there is no
            # point sending — those users wait for the template loop.
            if last_active < window_floor:
                stats["window_closed"] += 1
                continue

            onboarding = ws.mode == "onboarding"
            # A nudge already sent since their last message — which stage was it?
            nudged = as_aware(ws.last_winback_at)
            early_done = nudged is not None and nudged >= last_active
            last_chance_done = early_done and (nudged - last_active) >= last_chance_age

            if silent_for >= last_chance_age and not last_chance_done:
                stage = "last_chance"
            elif onboarding and silent_for >= early_age and not early_done:
                stage = "early"
            elif early_done or last_chance_done:
                stats["already_nudged"] += 1
                continue
            else:
                stats["too_early"] += 1
                continue

            if recently_pinged(ws, now):
                stats["already_nudged"] += 1
                continue

            # Anyone with a real match run belongs to the apply-follow-up loop.
            if ws.last_match_session_id is not None:
                ms = (
                    db.query(MatchSession)
                    .filter(MatchSession.id == ws.last_match_session_id)
                    .first()
                )
                if ms is not None and (ms.total_matched or 0) > 0:
                    stats["has_match_run"] += 1
                    continue

            if not onboarding:
                body, buttons = _no_match_nudge(ws)
            elif stage == "early":
                body, buttons = _early_onboarding_nudge(ws)
            else:
                body, buttons = _last_chance_onboarding_nudge(ws)

            if buttons:
                await _send_whatsapp_buttons(ws.phone_number, body, buttons)
            else:
                # Mid-onboarding, any reply continues the flow — buttons would
                # only compete with the question the AI is waiting on.
                await _send_whatsapp(ws.phone_number, body)
                # Record it as a turn the assistant took, so when they do reply
                # the onboarding AI reads "…want to finish?" / "yes" instead of
                # mistaking the answer for a reply to the last field question.
                _remember_assistant_turn(ws, body)

            ws.last_winback_at = now
            db.commit()
            stats["sent"] += 1
            stats[f"sent_{stage}"] += 1
            record_server_event(
                ws.phone_number, "window_winback_sent",
                f"{stage}:{'onboarding' if onboarding else 'no_match'}",
            )
    finally:
        db.close()

    if stats["sent"]:
        log.info(
            "Window win-back sweep done | checked=%d | sent=%d "
            "(early=%d last_chance=%d) | window_closed=%d | already_nudged=%d",
            stats["checked"], stats["sent"], stats["sent_early"],
            stats["sent_last_chance"], stats["window_closed"], stats["already_nudged"],
        )
    return stats


async def window_winback_loop() -> None:
    """Background asyncio task started at API startup."""
    interval_seconds = settings.WINDOW_WINBACK_CHECK_INTERVAL_HOURS * 60 * 60
    # Let DB init settle before the first sweep.
    await asyncio.sleep(480)
    while True:
        try:
            await run_window_winbacks_once()
        except Exception as exc:
            log.error("Window win-back sweep failed | error=%s", exc)
        await asyncio.sleep(interval_seconds)
