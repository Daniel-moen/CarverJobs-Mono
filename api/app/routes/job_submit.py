"""
User-facing job submission.

- Crew + agencies + admin may submit jobs (text, screenshots, or guided form).
- The crew flow earns +1 token on success (legacy behaviour); agencies do not.
- Every submitted job records `posted_by_user_id` so the agency dashboard
  can list its own submissions and admins can audit / bulk-action.
"""
import asyncio
import json as _json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from app import metrics, models
from app.database import get_db
from app.logger import get_logger
from app.security import require_agency_or_admin_session, require_poster_session
from app.services.credits import award_job_post_credit
from app.settings import settings

from app.routes.scraper import (
    ImportJobRequest,
    _IMAGE_EXTENSIONS,
    _IMAGE_MIME_TYPES,
    _MAX_IMPORT_IMAGE_BYTES,
    _run_import_pipeline,
    _save_job_from_ai_fields,
    _shape_import_response,
)
from app.schemas import AgencyJobFormRequest

log = get_logger("carver.job_submit")
_limiter = Limiter(key_func=get_remote_address)

# Vision submit: several screenshots of one long listing (website); cap size/count for safety.
_MAX_SUBMIT_IMAGE_COUNT = 6
_MAX_SUBMIT_TOTAL_BYTES = 24 * 1024 * 1024

router = APIRouter(prefix="/jobs/submit", tags=["job-submit"])


def _poster_meta(session: dict, db: Session) -> tuple[int | None, str | None]:
    """Resolve (user_id, agency_name) for the calling session, if available.

    Admins typing into the dashboard pass through with user_id=None; that
    matches today's behaviour and keeps admin actions out of the agency
    dashboard listings.
    """
    role = session.get("role")
    user_id = session.get("user_id")
    agency_name: str | None = None
    if role == "agency" and user_id:
        agency_name = (
            db.query(models.User.agency_name)
            .filter(models.User.id == user_id)
            .scalar()
        )
    return (user_id if role in ("crew", "agency") else None), agency_name


@router.post("/text", status_code=status.HTTP_201_CREATED)
@_limiter.limit("10/minute")
async def crew_submit_text(
    request: Request,
    payload: ImportJobRequest,
    session: dict = Depends(require_poster_session),
    db: Session = Depends(get_db),
):
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured.",
        )

    user_id, agency_name = _poster_meta(session, db)

    result = await asyncio.to_thread(
        _run_import_pipeline,
        text=payload.text,
        url=payload.url,
        source="agency_submit" if session.get("role") == "agency" else "website_submit",
        posted_by_user_id=user_id,
        posted_by_agency=agency_name,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The AI determined this is not a job posting. No record was created.",
        )

    if isinstance(result, dict) and result.get("duplicate"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This job is already on the board (id={result['id']}).",
        )

    user_key = session["sub"]
    new_bal = 0
    if session.get("role") == "crew":
        new_bal = award_job_post_credit(db, user_key)["balance"]
    log.info("Job submit (text) | id=%d | role=%s | sub=%s…",
             result.id, session.get("role"), (user_key or "")[:12])
    metrics.increment("manual_job_imports")

    out = _shape_import_response(result)
    out["credits_balance"] = new_bal
    return out


@router.post("/image", status_code=status.HTTP_201_CREATED)
@_limiter.limit("10/minute")
async def crew_submit_image(
    request: Request,
    url: str = Form(""),
    session: dict = Depends(require_poster_session),
    db: Session = Depends(get_db),
):
    from app.services.ai_client import review_job_images
    from app.services.ai_job_reviewer import _SYSTEM_PROMPT

    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured.",
        )

    form = await request.form()
    raw_list = form.getlist("files")
    if not raw_list:
        single = form.get("file")
        raw_list = [single] if single is not None else []

    uploadables = [f for f in raw_list if isinstance(f, UploadFile)]
    if not uploadables:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No image file(s). Send one or more images as form field 'files', or a single 'file'.",
        )
    if len(uploadables) > _MAX_SUBMIT_IMAGE_COUNT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many images (max {_MAX_SUBMIT_IMAGE_COUNT}).",
        )

    image_payloads: list[tuple[bytes, str]] = []
    total = 0
    for uf in uploadables:
        suffix = Path(uf.filename or "").suffix.lower()
        if suffix not in _IMAGE_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported image file extension on one of the uploads.",
            )
        if uf.content_type and uf.content_type not in _IMAGE_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported image MIME type on one of the uploads.",
            )
        contents = await uf.read()
        if not contents:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One of the uploads was empty.")
        if len(contents) > _MAX_IMPORT_IMAGE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Each image must be 8 MB or less.",
            )
        total += len(contents)
        if total > _MAX_SUBMIT_TOTAL_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Combined image size is too large (max 24 MB total).",
            )
        mime = uf.content_type or "image/png"
        image_payloads.append((contents, mime))

    raw_json = await asyncio.to_thread(
        review_job_images,
        api_key=settings.OPENAI_API_KEY,
        images=image_payloads,
        model=settings.OPENAI_MODEL,
        system_prompt=_SYSTEM_PROMPT,
    )

    try:
        parsed = _json.loads(raw_json)
    except (_json.JSONDecodeError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="AI could not parse the screenshot content.",
        )

    if not parsed.get("is_job"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="AI determined this is not a job posting.",
        )

    parsed.pop("is_job", None)

    user_id, agency_name = _poster_meta(session, db)
    is_agency = session.get("role") == "agency"

    result = await asyncio.to_thread(
        _save_job_from_ai_fields,
        ai_fields=parsed,
        url=url.strip(),
        source="agency_submit_screenshot" if is_agency else "website_submit_screenshot",
        posted_by_user_id=user_id,
        posted_by_agency=agency_name,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not save the job. No record was created.",
        )
    if isinstance(result, dict) and result.get("duplicate"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This job is already on the board (id={result['id']}).",
        )

    user_key = session["sub"]
    new_bal = 0
    if session.get("role") == "crew":
        new_bal = award_job_post_credit(db, user_key)["balance"]
    log.info("Job submit (image) | id=%d | role=%s | sub=%s…",
             result.id, session.get("role"), (user_key or "")[:12])
    metrics.increment("manual_job_imports")

    return {
        "ok": True,
        "job": _shape_import_response(result),
        "ai_extracted": {
            "title": parsed.get("title"),
            "role": parsed.get("role"),
            "location": parsed.get("location"),
            "description": parsed.get("description"),
        },
        "credits_balance": new_bal,
    }


@router.post("/form", status_code=status.HTTP_201_CREATED)
@_limiter.limit("20/minute")
def crew_submit_form(
    request: Request,
    payload: AgencyJobFormRequest,
    session: dict = Depends(require_poster_session),
    db: Session = Depends(get_db),
):
    """Guided structured form — no AI parsing, just validate + dedup + save."""
    from app.services.job_sync import _content_hash, _job_fingerprint

    user_id, agency_name = _poster_meta(session, db)
    is_agency = session.get("role") == "agency"

    fields = payload.model_dump(exclude_none=False)
    fields["status"] = "open"
    fields["source"] = "agency_form" if is_agency else "website_form"
    fields["auto_apply_enabled"] = False
    if user_id is not None:
        fields["posted_by_user_id"] = user_id
    if agency_name:
        fields["posted_by_agency"] = agency_name
        if not fields.get("recruiter_agency"):
            fields["recruiter_agency"] = agency_name

    text_for_hash = "|".join([
        (fields.get("title") or "").strip().lower(),
        (fields.get("role") or "").strip().lower(),
        (fields.get("yacht") or "").strip().lower(),
        (fields.get("location") or "").strip().lower(),
        (fields.get("description") or "").strip().lower(),
    ])
    if text_for_hash.strip("|"):
        fields["content_hash"] = _content_hash(text_for_hash)
    fields["job_fingerprint"] = _job_fingerprint(
        fields.get("role"),
        fields.get("location"),
        fields.get("start_date"),
    )

    if fields.get("content_hash"):
        existing = db.query(models.Job.id).filter(models.Job.content_hash == fields["content_hash"]).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"This job is already on the board (id={existing[0]}).",
            )
    if fields.get("job_fingerprint"):
        existing = db.query(models.Job.id).filter(models.Job.job_fingerprint == fields["job_fingerprint"]).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"This job is already on the board (id={existing[0]}).",
            )

    job = models.Job(**fields)
    db.add(job)
    db.commit()
    db.refresh(job)

    user_key = session["sub"]
    new_bal = 0
    if session.get("role") == "crew":
        new_bal = award_job_post_credit(db, user_key)["balance"]
    log.info("Job submit (form) | id=%d | role=%s | sub=%s…",
             job.id, session.get("role"), (user_key or "")[:12])
    metrics.increment("manual_job_imports")

    out = _shape_import_response(job)
    out["credits_balance"] = new_bal
    return out


@router.get("/mine")
def list_my_submissions(
    session: dict = Depends(require_agency_or_admin_session),
    db: Session = Depends(get_db),
):
    """Return jobs posted by the calling user (agency dashboard)."""
    user_id = session.get("user_id")
    if not user_id:
        return {"ok": True, "jobs": []}

    rows = (
        db.query(models.Job)
        .filter(models.Job.posted_by_user_id == user_id)
        .order_by(models.Job.created_at.desc())
        .limit(200)
        .all()
    )
    job_ids = [j.id for j in rows]

    # Engagement counts — unique users matched / unique users who drafted an
    # email per job. Two grouped queries scoped to the agency's own jobs.
    matches: dict[int, int] = {}
    drafts: dict[int, int] = {}
    if job_ids:
        match_rows = (
            db.query(
                models.MatchSessionResult.job_id,
                func.count(distinct(models.MatchSession.user_key)),
            )
            .join(
                models.MatchSession,
                models.MatchSession.id == models.MatchSessionResult.session_id,
            )
            .filter(
                models.MatchSessionResult.job_id.in_(job_ids),
                models.MatchSessionResult.matched.is_(True),
            )
            .group_by(models.MatchSessionResult.job_id)
            .all()
        )
        matches = {jid: count for jid, count in match_rows}

        draft_rows = (
            db.query(
                models.JobDraftEvent.job_id,
                func.count(distinct(models.JobDraftEvent.user_key)),
            )
            .filter(models.JobDraftEvent.job_id.in_(job_ids))
            .group_by(models.JobDraftEvent.job_id)
            .all()
        )
        drafts = {jid: count for jid, count in draft_rows}

    jobs = [
        {
            "id": j.id,
            "title": j.title,
            "role": j.role,
            "yacht": j.yacht,
            "location": j.location,
            "status": j.status,
            "source": j.source,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "match_count": int(matches.get(j.id, 0)),
            "draft_count": int(drafts.get(j.id, 0)),
        }
        for j in rows
    ]
    return {"ok": True, "jobs": jobs}
