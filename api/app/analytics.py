"""
Analytics store — persists frontend interaction events to SQLite and keeps
in-memory counters for fast dashboard queries.

Events are written to the `analytics_events` table (survives restarts) and
also aggregated into in-memory counters that power the real-time dashboard.
On startup the in-memory counters are rebuilt from the DB.
"""
import logging
import threading
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import AnalyticsEvent

_lock = threading.Lock()

_page_views: Counter = Counter()
_button_clicks: Counter = Counter()
_chat_events: Counter = Counter()
_event_types: Counter = Counter()
_total_events: int = 0
log = logging.getLogger("carver.analytics")


def _reset_counters_locked() -> None:
    global _total_events
    _page_views.clear()
    _button_clicks.clear()
    _chat_events.clear()
    _event_types.clear()
    _total_events = 0


def _rebuild_counters() -> None:
    """Rebuild in-memory counters from the database on startup."""
    global _total_events
    rows = []
    db: Session = SessionLocal()
    try:
        rows = db.query(
            AnalyticsEvent.event_type,
            AnalyticsEvent.page,
            AnalyticsEvent.label,
            func.count(AnalyticsEvent.id),
        ).group_by(
            AnalyticsEvent.event_type,
            AnalyticsEvent.page,
            AnalyticsEvent.label,
        ).all()
    except Exception:
        log.exception("Failed rebuilding analytics counters from DB")
        return
    finally:
        db.close()
    with _lock:
        _reset_counters_locked()

        for event_type, page, label, count in rows:
            _event_types[event_type] += count
            _total_events += count
            if event_type == "page_view" and page:
                _page_views[page] += count
            elif event_type == "click" and label:
                _button_clicks[label] += count
            elif event_type in ("chat_send", "chat_receive"):
                _chat_events[event_type] += count


_rebuild_counters()


def record_events(events: list[dict], db: Session | None = None) -> int:
    """Ingest a batch of frontend analytics events. Returns count ingested."""
    global _total_events
    own_db = db is None
    if own_db:
        db = SessionLocal()

    added = 0
    try:
        with _lock:
            for ev in events:
                event_type = ev.get("type", "unknown")
                session_id = ev.get("session_id", "unknown")
                _event_types[event_type] += 1
                _total_events += 1

                if event_type == "page_view":
                    _page_views[ev.get("page", "unknown")] += 1
                elif event_type == "click":
                    _button_clicks[ev.get("label", "unknown")] += 1
                elif event_type in ("chat_send", "chat_receive"):
                    _chat_events[event_type] += 1

                db.add(AnalyticsEvent(
                    session_id=session_id,
                    event_type=event_type,
                    page=ev.get("page"),
                    label=ev.get("label"),
                    value=str(ev.get("value")) if ev.get("value") is not None else None,
                    client_ts=ev.get("ts"),
                ))
                added += 1
        db.commit()
    except Exception:
        log.exception("Failed to record analytics events batch")
        db.rollback()
    finally:
        if own_db:
            db.close()
    return added


def record_server_event(user_key: str, name: str, value: str | None = None) -> None:
    """Persist a server-side funnel event to analytics_events.

    Durable counterpart to the in-memory `metrics` counters (which reset on
    every deploy): funnel milestones like onboarding completion, magic-link
    logins and match runs must survive restarts to be measurable at all.
    Best-effort — never raises into the calling flow.
    """
    record_events([{
        "type": "funnel_server",
        "session_id": (user_key or "unknown")[:40],
        "label": name,
        "value": value,
    }])


def get_analytics(db: Session | None = None) -> dict:
    """Return aggregated analytics data for the dashboard."""
    with _lock:
        top_pages = _page_views.most_common(20)
        top_clicks = _button_clicks.most_common(20)

        return {
            "total_events": _total_events,
            "event_types": dict(_event_types),
            "page_views": {
                "total": sum(_page_views.values()),
                "by_page": [{"page": p, "count": c} for p, c in top_pages],
            },
            "button_clicks": {
                "total": sum(_button_clicks.values()),
                "by_label": [{"label": l, "count": c} for l, c in top_clicks],
            },
            "chat": {
                "messages_sent": _chat_events.get("chat_send", 0),
                "messages_received": _chat_events.get("chat_receive", 0),
            },
        }


def get_user_flows(limit: int = 20, db: Session | None = None) -> list[dict]:
    """
    Return recent user session flows. Each flow is a session with its
    ordered list of events (page views + key interactions).
    """
    own_db = db is None
    if own_db:
        db = SessionLocal()

    try:
        recent_sessions = (
            db.query(AnalyticsEvent.session_id, func.max(AnalyticsEvent.created_at).label("last_seen"))
            .group_by(AnalyticsEvent.session_id)
            .order_by(desc("last_seen"))
            .limit(limit)
            .all()
        )

        flows = []
        for session_id, last_seen in recent_sessions:
            events = (
                db.query(AnalyticsEvent)
                .filter(AnalyticsEvent.session_id == session_id)
                .order_by(AnalyticsEvent.created_at.asc())
                .all()
            )
            flows.append({
                "session_id": session_id[:8],
                "event_count": len(events),
                "started_at": events[0].created_at.isoformat() if events else None,
                "last_seen": last_seen.isoformat() if last_seen else None,
                "events": [
                    {
                        "type": e.event_type,
                        "page": e.page,
                        "label": e.label,
                        "ts": e.client_ts or (e.created_at.isoformat() if e.created_at else None),
                    }
                    for e in events
                ],
                "pages": [e.page for e in events if e.event_type == "page_view" and e.page],
            })
        return flows
    finally:
        if own_db:
            db.close()


def get_page_transitions(db: Session | None = None) -> list[dict]:
    """
    Compute page-to-page transition counts across all sessions.
    Returns sorted list of {from, to, count}.
    """
    own_db = db is None
    if own_db:
        db = SessionLocal()

    try:
        sessions = (
            db.query(AnalyticsEvent.session_id)
            .filter(AnalyticsEvent.event_type == "page_view")
            .group_by(AnalyticsEvent.session_id)
            .having(func.count(AnalyticsEvent.id) > 1)
            .all()
        )

        transitions: Counter = Counter()
        for (session_id,) in sessions:
            pages = (
                db.query(AnalyticsEvent.page)
                .filter(
                    AnalyticsEvent.session_id == session_id,
                    AnalyticsEvent.event_type == "page_view",
                )
                .order_by(AnalyticsEvent.created_at.asc())
                .all()
            )
            page_list = [p[0] for p in pages if p[0]]
            for i in range(len(page_list) - 1):
                if page_list[i] != page_list[i + 1]:
                    transitions[(page_list[i], page_list[i + 1])] += 1

        return sorted(
            [{"from": f, "to": t, "count": c} for (f, t), c in transitions.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:30]
    finally:
        if own_db:
            db.close()
