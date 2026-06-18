"""Self-contained admin dashboard panel — data + serving layer.

This is a fresh, standalone admin dashboard (deliberately independent of the
legacy ``/admin/stats`` endpoint and the old Svelte StatusPage). It exposes a
single rich metrics endpoint plus static-file serving for the panel UI, all
served same-origin by FastAPI so the admin session cookie applies.

Two routers (mirrors ``app/routes/admin.py``):
  * ``router``        — admin-gated JSON metrics (``/admin/dashboard/metrics``)
  * ``public_router`` — un-gated static file serving for the panel HTML/CSS/JS,
                        which must load before the admin has a session cookie so
                        the login form can render.
"""

import pathlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.logger import get_logger
from app.models import (
  ContactUnlock,
  CreditAccount,
  Document,
  FeedbackSubmission,
  Job,
  MatchSession,
  Subscription,
  User,
  WhatsAppMessage,
  WhatsAppSession,
)
from app.security import require_admin_session

log = get_logger("carver.admin_dashboard")

# Successful-payment status. The Yoco webhook (routes/subscription.py, the
# payment.succeeded branch) sets ``sub.status = "completed"`` once a payment
# clears, so "completed" is the authoritative "paid" marker — NOT "active" or
# "complete". We key all revenue maths off this single value.
PAID_STATUS = "completed"

router = APIRouter(
  prefix="/admin/dashboard",
  tags=["admin-dashboard"],
  dependencies=[Depends(require_admin_session)],
)

# Public router: NO admin dependency — the panel HTML/CSS/JS must load before
# the admin has a session cookie so the login form can render same-origin.
public_router = APIRouter(tags=["admin-dashboard-ui"])

_STATIC = pathlib.Path(__file__).resolve().parent.parent / "static" / "admin"


def _iso(dt) -> str | None:
  return dt.isoformat() if dt else None


@router.get("/metrics")
def get_dashboard_metrics(
  days: int = Query(30, ge=1, le=365),
  db: Session = Depends(get_db),
):
  """Aggregate signup / revenue / token / message / engagement metrics.

  Returns the frozen JSON contract consumed by the dashboard UI. All queries
  are wrapped so a DB failure surfaces a clean 500 rather than a stack trace.
  """
  now = datetime.now(timezone.utc)

  try:
    # ── Signups ────────────────────────────────────────────────────────────
    users_total = db.query(func.count(User.id)).scalar() or 0
    # Website users = User rows whose email looks like an email (contains '@').
    users_website = (
      db.query(func.count(User.id)).filter(User.email.like("%@%")).scalar() or 0
    )
    # WhatsApp users = WhatsAppSession rows (phone-keyed onboarding/chat).
    wa_users = db.query(func.count(WhatsAppSession.phone_number)).scalar() or 0

    role_rows = db.query(User.role, func.count(User.id)).group_by(User.role).all()
    by_role = {"crew": 0, "agency": 0, "admin": 0}
    for role, count in role_rows:
      by_role[role or "unknown"] = count

    active_users = (
      db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0
    )
    subscribed_users = (
      db.query(func.count(User.id)).filter(User.is_subscribed.is_(True)).scalar() or 0
    )

    recent_user_rows = (
      db.query(User).order_by(User.created_at.desc(), User.id.desc()).limit(25).all()
    )
    recent_signups = [
      {
        "id": u.id,
        "name": u.full_name,
        "identifier": u.email,
        "role": u.role,
        "source": "website",
        "created_at": _iso(u.created_at),
      }
      for u in recent_user_rows
    ]

    # ── Signup timeseries (Python-side bucketing for SQLite portability) ─────
    # Zero-fill the last `days` calendar days (UTC), oldest→newest.
    start_date = (now - timedelta(days=days - 1)).date()
    buckets: dict[str, dict] = {}
    for i in range(days):
      d = (start_date + timedelta(days=i)).isoformat()
      buckets[d] = {"date": d, "website": 0, "whatsapp": 0}

    window_start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)

    for (created_at,) in db.query(User.created_at).filter(User.created_at >= window_start).all():
      if created_at is None:
        continue
      key = created_at.astimezone(timezone.utc).date().isoformat()
      if key in buckets:
        buckets[key]["website"] += 1

    for (created_at,) in (
      db.query(WhatsAppSession.created_at).filter(WhatsAppSession.created_at >= window_start).all()
    ):
      if created_at is None:
        continue
      key = created_at.astimezone(timezone.utc).date().isoformat()
      if key in buckets:
        buckets[key]["whatsapp"] += 1

    timeseries = [buckets[k] for k in sorted(buckets.keys())]

    # ── Revenue ──────────────────────────────────────────────────────────────
    transactions_total = db.query(func.count(Subscription.id)).scalar() or 0

    sub_status_rows = (
      db.query(Subscription.status, func.count(Subscription.id))
      .group_by(Subscription.status)
      .all()
    )
    # Real group-by of whatever statuses exist (contract keys are illustrative).
    by_status = {row[0] or "unknown": row[1] for row in sub_status_rows}

    # amount is stored as a string ZAR value — sum defensively in Python,
    # skipping any non-numeric values. Only "completed" rows count as paid.
    paid_rows = (
      db.query(Subscription.user_key, Subscription.amount)
      .filter(Subscription.status == PAID_STATUS)
      .all()
    )
    total_paid = 0.0
    paying_keys = set()
    for user_key, amount in paid_rows:
      try:
        total_paid += float(amount)
      except (TypeError, ValueError):
        log.warning("Non-numeric subscription amount skipped | user_key=%s | amount=%r", user_key, amount)
      paying_keys.add(user_key)

    recent_payment_rows = (
      db.query(Subscription)
      .order_by(Subscription.created_at.desc(), Subscription.id.desc())
      .limit(15)
      .all()
    )
    recent_payments = [
      {
        "user_key": s.user_key,
        "amount": s.amount,
        "status": s.status,
        "created_at": _iso(s.created_at),
      }
      for s in recent_payment_rows
    ]

    # ── Tokens ────────────────────────────────────────────────────────────────
    balance_outstanding = db.query(func.coalesce(func.sum(CreditAccount.balance), 0)).scalar() or 0
    accounts = db.query(func.count(CreditAccount.id)).scalar() or 0
    spent_on_unlocks = db.query(func.coalesce(func.sum(ContactUnlock.cost_tokens), 0)).scalar() or 0
    unlocks_count = db.query(func.count(ContactUnlock.id)).scalar() or 0

    # ── Messages ──────────────────────────────────────────────────────────────
    wa_total = db.query(func.count(WhatsAppMessage.id)).scalar() or 0
    inbound = (
      db.query(func.count(WhatsAppMessage.id))
      .filter(WhatsAppMessage.direction == "inbound")
      .scalar()
      or 0
    )
    outbound = (
      db.query(func.count(WhatsAppMessage.id))
      .filter(WhatsAppMessage.direction == "outbound")
      .scalar()
      or 0
    )
    active_sessions = db.query(func.count(WhatsAppSession.phone_number)).scalar() or 0
    mode_rows = (
      db.query(WhatsAppSession.mode, func.count(WhatsAppSession.phone_number))
      .group_by(WhatsAppSession.mode)
      .all()
    )
    sessions_by_mode = {"onboarding": 0, "chat": 0}
    for mode, count in mode_rows:
      sessions_by_mode[mode or "unknown"] = count

    # ── Engagement ────────────────────────────────────────────────────────────
    jobs_total = db.query(func.count(Job.id)).scalar() or 0
    match_sessions = db.query(func.count(MatchSession.id)).scalar() or 0
    feedback_submissions = db.query(func.count(FeedbackSubmission.id)).scalar() or 0
    documents = db.query(func.count(Document.id)).scalar() or 0

  except Exception as exc:
    log.error("Admin dashboard metrics query failed: %s", exc)
    raise HTTPException(
      status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
      detail="Could not load dashboard metrics.",
    ) from exc

  return {
    "ok": True,
    "generated_at": now.isoformat(),
    "window_days": days,
    "signups": {
      "total": users_total,
      "website": users_website,
      "whatsapp": wa_users,
      "by_role": by_role,
      "active_users": active_users,
      "subscribed_users": subscribed_users,
      "recent": recent_signups,
      "timeseries": timeseries,
    },
    "revenue": {
      "currency": "ZAR",
      "total_paid": round(total_paid, 2),
      "paying_customers": len(paying_keys),
      "transactions_total": transactions_total,
      "transactions_paid": len(paid_rows),
      "by_status": by_status,
      "recent_payments": recent_payments,
    },
    "tokens": {
      "balance_outstanding": balance_outstanding,
      "accounts": accounts,
      "spent_on_unlocks": spent_on_unlocks,
      "unlocks_count": unlocks_count,
    },
    "messages": {
      "whatsapp_total": wa_total,
      "inbound": inbound,
      "outbound": outbound,
      "active_sessions": active_sessions,
      "sessions_by_mode": sessions_by_mode,
    },
    "engagement": {
      "jobs_total": jobs_total,
      "match_sessions": match_sessions,
      "feedback_submissions": feedback_submissions,
      "documents": documents,
    },
  }


# ── Panel static files (un-gated so the login form can render) ────────────────

@public_router.get("/admin/dashboard")
def serve_dashboard_html():
  path = _STATIC / "index.html"
  if not path.is_file():
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard UI not found.")
  return FileResponse(path, media_type="text/html")


@public_router.get("/admin/dashboard.css")
def serve_dashboard_css():
  path = _STATIC / "dashboard.css"
  if not path.is_file():
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard CSS not found.")
  return FileResponse(path, media_type="text/css")


@public_router.get("/admin/dashboard.js")
def serve_dashboard_js():
  path = _STATIC / "dashboard.js"
  if not path.is_file():
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard JS not found.")
  return FileResponse(path, media_type="application/javascript")
