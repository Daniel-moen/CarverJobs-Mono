from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import analytics, flags, metrics
from app.database import get_db
from app.error_codes import CRV_1005, CRV_5001, CRV_5002, CRV_5003
from app.logger import get_logger
from app.models import ErrorLog, Job, User, WhatsAppMagicToken, WhatsAppSession
from app.security import require_admin_session
from app.services.ai_client import AIClientError, call_openai
from app.settings import settings

log = get_logger("carver.admin")
_limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_session)])

# Public router: no authentication required.  Used for analytics event
# ingestion from unauthenticated pages (landing page, login screen).
public_router = APIRouter(prefix="/admin", tags=["analytics"])


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
@_limiter.limit("30/minute")
def get_stats(request: Request, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    uptime_seconds = int((now - metrics.server_started_at).total_seconds())

    try:
        users_total  = db.query(func.count(User.id)).scalar() or 0
        users_active = db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0
        role_rows    = db.query(User.role, func.count(User.id)).group_by(User.role).all()
        users_by_role = {row[0]: row[1] for row in role_rows}

        jobs_total   = db.query(func.count(Job.id)).scalar() or 0
        status_rows  = db.query(Job.status, func.count(Job.id)).group_by(Job.status).all()
        jobs_by_status = {row[0]: row[1] for row in status_rows}

        wa_sessions_total = db.query(func.count(WhatsAppSession.phone_number)).scalar() or 0
        wa_mode_rows      = db.query(WhatsAppSession.mode, func.count(WhatsAppSession.phone_number)).group_by(WhatsAppSession.mode).all()
        wa_sessions_by_mode = {row[0]: row[1] for row in wa_mode_rows}
        wa_tokens_total   = db.query(func.count(WhatsAppMagicToken.token)).scalar() or 0
        wa_tokens_used    = db.query(func.count(WhatsAppMagicToken.token)).filter(WhatsAppMagicToken.used.is_(True)).scalar() or 0
    except Exception as exc:
        log.error("Admin stats DB query failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not load statistics.",
            headers={"X-Error-Code": CRV_5001},
        ) from exc

    log.debug("Stats requested | users=%d | jobs=%d", users_total, jobs_total)

    return {
        "ok": True,
        "uptime_seconds": uptime_seconds,
        "server_started_at": metrics.server_started_at.isoformat(),
        "db": {
            "users_total": users_total,
            "users_active": users_active,
            "users_by_role": users_by_role,
            "jobs_total": jobs_total,
            "jobs_by_status": jobs_by_status,
            "whatsapp_sessions_total": wa_sessions_total,
            "whatsapp_sessions_by_mode": wa_sessions_by_mode,
            "whatsapp_magic_tokens_total": wa_tokens_total,
            "whatsapp_magic_tokens_used": wa_tokens_used,
        },
        "events": metrics.snapshot(),
        "errors_by_module": metrics.errors_by_module_snapshot(),
        "time_series": metrics.history(),
    }


# ── Feature flags ─────────────────────────────────────────────────────────────

@router.get("/flags")
def get_flags():
    return {
        "ok": True,
        "flags": flags.get_all(),
        "labels": flags.LABELS,
    }


class FlagUpdate(BaseModel):
    key: str
    enabled: bool


@router.patch("/flags")
@_limiter.limit("30/minute")
def update_flag(request: Request, payload: FlagUpdate):
    log.warning("Feature flag changed | key=%s | enabled=%s", payload.key, payload.enabled)
    if not flags.set_flag(payload.key, payload.enabled):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown feature flag.",
            headers={"X-Error-Code": CRV_5002},
        )
    return {"ok": True, "flags": flags.get_all()}


# ── Error log ─────────────────────────────────────────────────────────────────

@router.get("/errors")
def get_error_logs(db: Session = Depends(get_db)):
    """Return the 50 most recent persisted error log entries."""
    rows = db.query(ErrorLog).order_by(ErrorLog.created_at.desc()).limit(50).all()
    return {
        "ok": True,
        "errors": [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "level": r.level,
                "status_code": r.status_code,
                "crv_code": r.crv_code,
                "method": r.method,
                "path": r.path,
                "module": r.module,
                "message": r.message,
                "traceback": r.traceback,
                "request_id": r.request_id,
                "client_ip": r.client_ip,
                "ai_analysis": r.ai_analysis,
            }
            for r in rows
        ],
    }


@router.post("/errors/{error_id}/analyze")
@_limiter.limit("10/minute")
def analyze_error(request: Request, error_id: int, db: Session = Depends(get_db)):
    """Ask OpenAI to identify the source and cause of a recorded error."""
    row = db.query(ErrorLog).filter(ErrorLog.id == error_id).first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Error log entry not found.",
            headers={"X-Error-Code": CRV_1005},
        )

    prompt_parts = [
        "You are a senior backend engineer reviewing a server error from the Carver API "
        "(a yacht crew recruitment platform built with FastAPI + SQLite).",
        "",
        "Error details:",
        f"  Timestamp  : {row.created_at}",
        f"  Method     : {row.method}  Path: {row.path}",
        f"  Module     : {row.module}",
        f"  HTTP status: {row.status_code}  CRV code: {row.crv_code}",
        f"  Message    : {row.message}",
    ]
    if row.traceback:
        prompt_parts += ["", "Python traceback:", row.traceback]

    prompt_parts += [
        "",
        "Provide a concise analysis (3–5 sentences) covering:",
        "1. Most likely root cause.",
        "2. Which file/function is responsible.",
        "3. Recommended fix or investigation step.",
    ]

    try:
        analysis = call_openai(
            api_key=settings.OPENAI_API_KEY or "",
            messages=[{"role": "user", "content": "\n".join(prompt_parts)}],
            model=settings.OPENAI_MODEL or "gpt-4o-mini",
            max_tokens=400,
            temperature=0.1,
        )
    except AIClientError as exc:
        log.error("AI error analysis failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach AI service for analysis.",
            headers={"X-Error-Code": getattr(exc, "crv_code", None) or CRV_5003},
        ) from exc

    row.ai_analysis = analysis
    db.commit()
    log.info("AI error analysis complete | error_id=%d", error_id)
    return {"ok": True, "analysis": analysis}


# ── Analytics ──────────────────────────────────────────────────────────────────

class AnalyticsEventSchema(BaseModel):
    type: str
    session_id: str | None = None
    page: str | None = None
    label: str | None = None
    value: Any = None
    ts: str | None = None


class AnalyticsBatch(BaseModel):
    events: list[AnalyticsEventSchema]


@public_router.post("/analytics")
@_limiter.limit("60/minute")
def post_analytics(request: Request, payload: AnalyticsBatch, db: Session = Depends(get_db)):
    count = analytics.record_events([ev.model_dump() for ev in payload.events], db=db)
    log.debug("Analytics ingested | events=%d", count)
    return {"ok": True, "ingested": count}


@router.get("/analytics")
def get_analytics():
    return {"ok": True, **analytics.get_analytics()}


@router.get("/analytics/flows")
def get_flows(db: Session = Depends(get_db)):
    flows = analytics.get_user_flows(limit=20, db=db)
    transitions = analytics.get_page_transitions(db=db)
    return {"ok": True, "flows": flows, "transitions": transitions}
