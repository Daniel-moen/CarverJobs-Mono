from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import Field, JsonValue
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import analytics, flags, go_routing, metrics, telnyx_inbound_buffer
from app.database import get_db
from app.error_codes import CRV_1005, CRV_5001, CRV_5002, CRV_5003, CRV_5004
from app.logger import get_logger
from app.models import ErrorLog, FeedbackSubmission, Job, User, WhatsAppMagicToken, WhatsAppMessage, WhatsAppSession
from app.schemas import APIModel, FeedbackSettingsResponse, FeedbackSettingsUpdate
from app.security import require_admin_session
from app.services.ai_client import AIClientError, call_openai
from app.services.feedback_settings import (
    get_feedback_setting,
    serialise_feedback_setting,
    update_feedback_setting,
)
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
        feedback_total    = db.query(func.count(FeedbackSubmission.id)).scalar() or 0
        feedback_by_source_rows = db.query(FeedbackSubmission.source, func.count(FeedbackSubmission.id)).group_by(FeedbackSubmission.source).all()
        feedback_by_source = {row[0]: row[1] for row in feedback_by_source_rows}
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
            "feedback_submissions_total": feedback_total,
            "feedback_submissions_by_source": feedback_by_source,
        },
        "events": metrics.snapshot(),
        "errors_by_module": metrics.errors_by_module_snapshot(),
        "time_series": metrics.history(),
    }


@router.get("/telnyx-inbound")
def get_telnyx_inbound_recent():
    """Recent inbound SMS captured by POST /telnyx/webhook (for OTP / debugging)."""
    return {"ok": True, "messages": telnyx_inbound_buffer.recent()}


@router.get("/whatsapp/messages")
def list_whatsapp_messages(
    limit: int = Query(default=50, ge=1, le=200),
    phone_number: str | None = Query(default=None, max_length=30),
    db: Session = Depends(get_db),
):
    query = db.query(WhatsAppMessage).order_by(WhatsAppMessage.id.desc())
    if phone_number:
        query = query.filter(WhatsAppMessage.phone_number == phone_number.strip())

    rows = query.limit(limit).all()
    return {
        "ok": True,
        "messages": [
            {
                "id": row.id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "phone_number": row.phone_number,
                "direction": row.direction,
                "message_type": row.message_type,
                "content": row.content,
                "meta_message_id": row.meta_message_id,
                "graph_phone_number_id": row.graph_phone_number_id,
            }
            for row in rows
        ],
    }


# ── Feature flags ─────────────────────────────────────────────────────────────

@router.get("/flags")
def get_flags():
    return {
        "ok": True,
        "flags": flags.get_all(),
        "labels": flags.LABELS,
    }


class FlagUpdate(APIModel):
    key: Annotated[str, Field(min_length=1, max_length=80)]
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


# ── Go canary routing (per-user) ──────────────────────────────────────────────

@router.get("/users/routing")
def list_user_routing(db: Session = Depends(get_db)):
    """List users pinned to the Go port (route_to_go = true)."""
    rows = db.query(User.id, User.email).filter(User.route_to_go.is_(True)).all()
    return {"ok": True, "flagged": [{"user_id": r[0], "email": r[1]} for r in rows]}


class UserRoutingUpdate(APIModel):
    route_to_go: bool


@router.patch("/users/{user_id}/routing")
@_limiter.limit("30/minute")
def set_user_routing(request: Request, user_id: int, payload: UserRoutingUpdate, db: Session = Depends(get_db)):
    """Flag/unflag a user so their traffic is served by the Go port (jobcarver-go)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
            headers={"X-Error-Code": CRV_5002},
        )
    user.route_to_go = payload.route_to_go
    db.commit()
    go_routing.flagged.set(user_id, payload.route_to_go)
    log.warning("user canary routing changed | user_id=%s | route_to_go=%s", user_id, payload.route_to_go)
    return {"ok": True, "user_id": user_id, "route_to_go": payload.route_to_go}


# ── Feedback campaign settings ────────────────────────────────────────────────

@router.get("/feedback/settings", response_model=FeedbackSettingsResponse)
def get_feedback_settings(db: Session = Depends(get_db)):
    setting = get_feedback_setting(db)
    return {"ok": True, **serialise_feedback_setting(setting)}


@router.patch("/feedback/settings", response_model=FeedbackSettingsResponse)
@_limiter.limit("20/minute")
def update_feedback_settings(
    request: Request,
    payload: FeedbackSettingsUpdate,
    db: Session = Depends(get_db),
):
    setting = update_feedback_setting(
        db,
        enabled=payload.enabled,
        target_mode=payload.target_mode,
        target_user_keys=payload.target_user_keys,
    )
    log.warning(
        "Feedback settings changed | enabled=%s | target_mode=%s | targets=%d",
        setting.enabled,
        setting.target_mode,
        len(payload.target_user_keys),
    )
    return {"ok": True, **serialise_feedback_setting(setting)}


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


# ── AI job review ──────────────────────────────────────────────────────────────

_JOB_REVIEW_PROMPT = """You are a strict quality checker for a yacht crew job board database. You will receive a batch of job listings as a JSON array. Each entry has an "id" and a "summary" string.

For EACH entry decide whether it is a GENUINE, SPECIFIC yacht crew job posting.

REJECT (not a real job) if ANY of these are true:
- It is a crew member seeking work (not an employer offering a position)
- It is an agency spam blast listing many roles without a specific yacht
- It is a training course ad, news article, discussion, or equipment sale
- It lacks basic job details (no specific role, no location, no start date/period)
- The description is gibberish, a test entry, or clearly non-job content
- It is a duplicate placeholder or template with no real information

ACCEPT (real job) if it describes a specific open crew position on a yacht with at least a role and some concrete details.

Return ONLY a JSON object with this shape — no markdown, no explanation:
{"results": [{"id": <int>, "is_job": <bool>, "reason": "<short reason>"}]}

Every input id MUST appear in the output."""


@router.post("/jobs/review")
@_limiter.limit("5/minute")
def review_jobs(request: Request, db: Session = Depends(get_db)):
    """AI-review all jobs in the DB; delete entries that are not real jobs."""
    import json as _json

    api_key = settings.OPENAI_API_KEY
    model = settings.OPENAI_MODEL or "gpt-4o-mini"

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI API key is not configured.",
            headers={"X-Error-Code": CRV_5004},
        )

    jobs = db.query(Job).all()
    if not jobs:
        return {"ok": True, "reviewed": 0, "deleted": 0, "deleted_jobs": []}

    def _summarise(job: Job) -> str:
        parts = [f"Title: {job.title}", f"Role: {job.role}"]
        if job.yacht:
            parts.append(f"Yacht: {job.yacht}")
        if job.location:
            parts.append(f"Location: {job.location}")
        if job.start_date:
            parts.append(f"Start: {job.start_date}")
        if job.description:
            parts.append(f"Description: {(job.description or '')[:300]}")
        return " | ".join(parts)

    BATCH_SIZE = 10
    deleted_jobs: list[dict] = []
    reviewed = 0
    failed_batches = 0

    for i in range(0, len(jobs), BATCH_SIZE):
        batch = jobs[i : i + BATCH_SIZE]
        payload = [{"id": j.id, "summary": _summarise(j)} for j in batch]

        try:
            content = call_openai(
                api_key=api_key,
                messages=[
                    {"role": "system", "content": _JOB_REVIEW_PROMPT},
                    {"role": "user", "content": _json.dumps(payload)},
                ],
                model=model,
                max_tokens=2000,
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            parsed = _json.loads(content)
            results = parsed.get("results", [])
        except (AIClientError, _json.JSONDecodeError, Exception) as exc:
            log.error("AI job review batch failed | batch=%d | error=%s", i // BATCH_SIZE, exc)
            reviewed += len(batch)
            failed_batches += 1
            continue

        reject_ids = {r["id"] for r in results if not r.get("is_job")}
        reviewed_ids = {r["id"] for r in results}

        for job in batch:
            reviewed += 1
            if job.id in reject_ids:
                reason = next((r.get("reason", "") for r in results if r["id"] == job.id), "")
                deleted_jobs.append({"id": job.id, "title": job.title, "reason": reason})
                db.delete(job)
            elif job.id not in reviewed_ids:
                log.warning("AI job review: job id=%d missing from AI response, skipping", job.id)

    db.commit()
    log.warning(
        "AI job review complete | total=%d | reviewed=%d | deleted=%d | failed_batches=%d",
        len(jobs), reviewed, len(deleted_jobs), failed_batches,
    )
    return {
        "ok": True,
        "total": len(jobs),
        "reviewed": reviewed,
        "deleted": len(deleted_jobs),
        "failed_batches": failed_batches,
        "deleted_jobs": deleted_jobs,
    }


# ── Analytics ──────────────────────────────────────────────────────────────────

class AnalyticsEventSchema(APIModel):
    type: Annotated[str, Field(min_length=1, max_length=80)]
    session_id: Annotated[str | None, Field(default=None, max_length=128)] = None
    page: Annotated[str | None, Field(default=None, max_length=300)] = None
    label: Annotated[str | None, Field(default=None, max_length=300)] = None
    value: JsonValue | None = None
    ts: Annotated[str | None, Field(default=None, max_length=64)] = None


class AnalyticsBatch(APIModel):
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


@router.delete("/jobs/duplicates")
def wipe_duplicate_jobs(db: Session = Depends(get_db)):
    """Delete duplicate jobs (same title+role+location), keeping the oldest of each group."""
    from sqlalchemy import func

    keep_subq = (
        db.query(func.min(Job.id).label("min_id"))
        .group_by(Job.title, Job.role, Job.location)
        .subquery()
    )
    keep_ids = [row[0] for row in db.query(keep_subq).all()]
    deleted = (
        db.query(Job)
        .filter(~Job.id.in_(keep_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    log.warning("Admin wiped duplicate jobs | deleted=%d", deleted)
    return {"ok": True, "deleted": deleted}


@router.delete("/whatsapp/sessions")
def wipe_whatsapp_sessions(db: Session = Depends(get_db)):
    """Delete all WhatsApp sessions and magic tokens (admin only)."""
    sessions_deleted = db.query(WhatsAppSession).delete()
    tokens_deleted = db.query(WhatsAppMagicToken).delete()
    db.commit()
    log.warning("Admin wiped WhatsApp data | sessions=%d | tokens=%d", sessions_deleted, tokens_deleted)
    return {"ok": True, "sessions_deleted": sessions_deleted, "tokens_deleted": tokens_deleted}
