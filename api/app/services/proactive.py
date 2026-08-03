"""Shared rules for bot-initiated ("proactive") WhatsApp sends.

Three loops now message users without being asked — job alerts, the next-day
"did you apply?" sweep, and the last-chance window win-back. They each read the
same two facts, so the facts live here rather than being re-derived (and
re-tuned) in three places:

* **The service window.** Meta only accepts a free-form send within 24h of the
  user's last inbound message. Everything outside it needs a paid, pre-approved
  template. 23h is the working limit, leaving margin for clock skew and the
  sweep interval.
* **The quiet gap.** Whatever the loops individually think is due, a user should
  not receive two unprompted messages within a few hours. Each loop stamps its
  own column; the gap is enforced against the most recent stamp of any of them.
"""
from datetime import datetime, timedelta, timezone

# Free-form sends only deliver inside Meta's 24h service window; 23h keeps margin.
SERVICE_WINDOW_HOURS = 23
# Minimum spacing between any two proactive messages to the same user.
MIN_GAP_HOURS = 6


def as_aware(dt: datetime | None) -> datetime | None:
    """Treat naive timestamps as UTC — SQLite round-trips drop the tzinfo."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def in_service_window(ws, now: datetime) -> bool:
    """True when a free-form message to this user would still be delivered."""
    last_active = as_aware(getattr(ws, "last_active_at", None))
    return last_active is not None and last_active >= now - timedelta(hours=SERVICE_WINDOW_HOURS)


def last_proactive_ping(ws) -> datetime | None:
    """Most recent bot-initiated message to this user, across every loop."""
    stamps = [
        as_aware(getattr(ws, "last_job_alert_at", None)),
        as_aware(getattr(ws, "last_apply_followup_at", None)),
        as_aware(getattr(ws, "last_winback_at", None)),
    ]
    known = [s for s in stamps if s is not None]
    return max(known) if known else None


def recently_pinged(ws, now: datetime, gap_hours: int = MIN_GAP_HOURS) -> bool:
    """True when another loop already messaged this user too recently."""
    last = last_proactive_ping(ws)
    return last is not None and last > now - timedelta(hours=gap_hours)
