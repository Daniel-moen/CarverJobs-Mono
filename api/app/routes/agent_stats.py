"""
Agent monitoring endpoint.

GET /agent/stats — returns platform-wide aggregate statistics for an
external AI agent to poll.  Authenticated via a static bearer token
(AGENT_API_TOKEN env var), not the normal session system.
"""

import hmac
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import cast, func, Numeric
from sqlalchemy.orm import Session

from app import metrics
from app.database import get_db
from app.error_codes import CRV_2004, CRV_5005, CRV_5006
from app.logger import get_logger
from app.models import (
    CreditAccount,
    CrewProfile,
    Document,
    ErrorLog,
    Job,
    MatchSession,
    MatchSessionResult,
    Subscription,
    User,
    WaitlistSignup,
    WhatsAppMagicToken,
    WhatsAppSession,
)
from app.settings import settings

log = get_logger("carver.agent_stats")
_limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/agent", tags=["agent"])


def _require_agent_token(request: Request) -> None:
    """Validate the bearer token against AGENT_API_TOKEN (timing-safe)."""
    if not settings.AGENT_API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent stats endpoint is not configured.",
            headers={"X-Error-Code": CRV_5005},
        )

    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""

    if not token or not hmac.compare_digest(token, settings.AGENT_API_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing agent token.",
            headers={"X-Error-Code": CRV_2004},
        )


@router.get("/stats", dependencies=[Depends(_require_agent_token)])
@_limiter.limit("10/minute")
def get_agent_stats(request: Request, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)
    uptime_seconds = int((now - metrics.server_started_at).total_seconds())

    try:
        # ── Users (website) ──────────────────────────────────────────────
        users_total = db.query(func.count(User.id)).scalar() or 0
        users_active = db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0
        users_subscribed = db.query(func.count(User.id)).filter(User.is_subscribed.is_(True)).scalar() or 0
        role_rows = db.query(User.role, func.count(User.id)).group_by(User.role).all()
        users_by_role = {r[0]: r[1] for r in role_rows}

        # ── WhatsApp users ───────────────────────────────────────────────
        wa_total = db.query(func.count(WhatsAppSession.phone_number)).scalar() or 0
        wa_mode_rows = (
            db.query(WhatsAppSession.mode, func.count(WhatsAppSession.phone_number))
            .group_by(WhatsAppSession.mode)
            .all()
        )
        wa_by_mode = {r[0]: r[1] for r in wa_mode_rows}
        wa_tokens_total = db.query(func.count(WhatsAppMagicToken.token)).scalar() or 0
        wa_tokens_used = (
            db.query(func.count(WhatsAppMagicToken.token))
            .filter(WhatsAppMagicToken.used.is_(True))
            .scalar() or 0
        )

        # ── Jobs ─────────────────────────────────────────────────────────
        jobs_total = db.query(func.count(Job.id)).scalar() or 0
        status_rows = db.query(Job.status, func.count(Job.id)).group_by(Job.status).all()
        jobs_by_status = {r[0]: r[1] for r in status_rows}
        source_rows = db.query(Job.source, func.count(Job.id)).group_by(Job.source).all()
        jobs_by_source = {(r[0] or "unknown"): r[1] for r in source_rows}
        jobs_last_24h = (
            db.query(func.count(Job.id)).filter(Job.created_at >= cutoff_24h).scalar() or 0
        )
        jobs_last_7d = (
            db.query(func.count(Job.id)).filter(Job.created_at >= cutoff_7d).scalar() or 0
        )

        # ── Matching ─────────────────────────────────────────────────────
        match_sessions_total = db.query(func.count(MatchSession.id)).scalar() or 0
        match_total_matched = (
            db.query(func.coalesce(func.sum(MatchSession.total_matched), 0)).scalar()
        )
        avg_compat = (
            db.query(func.avg(MatchSessionResult.compatibility))
            .filter(MatchSessionResult.matched.is_(True))
            .scalar()
        )

        # ── Good to know ─────────────────────────────────────────────────
        waitlist_total = db.query(func.count(WaitlistSignup.id)).scalar() or 0
        profiles_total = db.query(func.count(CrewProfile.id)).scalar() or 0
        documents_total = db.query(func.count(Document.id)).scalar() or 0
        errors_last_24h = (
            db.query(func.count(ErrorLog.id)).filter(ErrorLog.created_at >= cutoff_24h).scalar() or 0
        )

        sub_status_rows = (
            db.query(Subscription.status, func.count(Subscription.id))
            .group_by(Subscription.status)
            .all()
        )
        subscriptions_by_status = {r[0]: r[1] for r in sub_status_rows}

        credits_total_balance = (
            db.query(func.coalesce(func.sum(CreditAccount.balance), 0)).scalar()
        )

        # ── Token purchases ──────────────────────────────────────────────
        completed_filter = Subscription.status == "completed"
        tokens_purchased_total = (
            db.query(func.count(Subscription.id)).filter(completed_filter).scalar() or 0
        )
        tokens_revenue_zar = (
            db.query(func.coalesce(func.sum(cast(Subscription.amount, Numeric)), 0))
            .filter(completed_filter)
            .scalar()
        )
        tokens_unique_buyers = (
            db.query(func.count(func.distinct(Subscription.user_key)))
            .filter(completed_filter)
            .scalar() or 0
        )

    except Exception as exc:
        log.error("Agent stats DB query failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load statistics.",
            headers={"X-Error-Code": CRV_5006},
        ) from exc

    events = metrics.snapshot()

    return {
        "ok": True,
        "generated_at": now.isoformat(),
        "uptime_seconds": uptime_seconds,
        "server_started_at": metrics.server_started_at.isoformat(),
        "users": {
            "website_total": users_total,
            "active": users_active,
            "subscribed": users_subscribed,
            "by_role": users_by_role,
            "whatsapp_total": wa_total,
            "whatsapp_by_mode": wa_by_mode,
            "whatsapp_magic_tokens": wa_tokens_total,
            "whatsapp_magic_tokens_used": wa_tokens_used,
        },
        "jobs": {
            "total": jobs_total,
            "by_status": jobs_by_status,
            "by_source": jobs_by_source,
            "added_last_24h": jobs_last_24h,
            "added_last_7d": jobs_last_7d,
        },
        "matching": {
            "sessions_total": match_sessions_total,
            "total_matched": match_total_matched,
            "avg_compatibility": round(avg_compat, 2) if avg_compat is not None else None,
        },
        "good_to_know": {
            "waitlist_signups": waitlist_total,
            "crew_profiles": profiles_total,
            "documents_uploaded": documents_total,
            "subscriptions_by_status": subscriptions_by_status,
            "credits_total_balance": credits_total_balance,
            "token_purchases": tokens_purchased_total,
            "token_revenue_zar": float(tokens_revenue_zar),
            "token_unique_buyers": tokens_unique_buyers,
            "errors_last_24h": errors_last_24h,
        },
        "api": {
            "requests_total": events.get("requests_total", 0),
            "whatsapp_messages": events.get("whatsapp_messages", 0),
            "crew_matches": events.get("crew_matches", 0),
            "avg_response_ms": events.get("avg_response_ms", 0),
            "avg_ai_response_ms": events.get("avg_ai_response_ms", 0),
        },
    }
