"""
Admin routes for scraper management.

  GET  /scraper/status        — APIFY scheduler state + last run result
  POST /scraper/trigger       — kick off a full Apify scrape + AI review cycle
  POST /scraper/import        — submit raw post text to AI review and save if valid
"""
import asyncio
from typing import Annotated
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app import metrics
from app.database import SessionLocal
from app.error_codes import CRV_6001, CRV_6002
from app.logger import get_logger
from app.scheduler import get_scraper_state, run_scrape_once
from app.schemas import APIModel
from app.security import require_admin_session
from app.settings import settings

log = get_logger("carver.routes.scraper")
_limiter = Limiter(key_func=get_remote_address)

router = APIRouter(
    prefix="/scraper",
    tags=["scraper"],
    dependencies=[Depends(require_admin_session)],
)


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
def scraper_status():
    """Return scraper configuration state and the last run result."""
    state = get_scraper_state()
    actor_ids = [a for a in settings.APIFY_ACTOR_IDS if a.strip()]
    start_urls = [u for u in settings.APIFY_START_URLS if u.strip()]

    # Build a list of active web scrapers for the dashboard
    web_scrapers: list[dict] = [
        {"name": "Dockwalk",     "enabled": settings.DOCKWALK_ENABLED,      "needs_proxy": True},
        {"name": "Yotspot",      "enabled": settings.WORKONAYACHT_ENABLED,   "needs_proxy": True},
        {"name": "Faststream",   "enabled": settings.FASTSTREAM_ENABLED,     "needs_proxy": False},
        {"name": "CrewFinders",  "enabled": settings.CREWFINDERS_ENABLED,    "needs_proxy": False},
        {"name": "Viking Crew",  "enabled": settings.VIKINGCREW_ENABLED,     "needs_proxy": True},
    ]
    scrape_do_ok = bool(settings.SCRAPE_DO_TOKEN)

    return {
        "ok": True,
        "configured": bool(settings.APIFY_API_KEY and actor_ids and start_urls),
        "actor_count": len(actor_ids),
        "url_count": len(start_urls),
        "web_scrapers": web_scrapers,
        "scrape_do_configured": scrape_do_ok,
        **state,
    }


# ── Trigger ───────────────────────────────────────────────────────────────────

@router.post("/trigger", status_code=status.HTTP_202_ACCEPTED)
@_limiter.limit("5/minute")
async def trigger_scrape(request: Request):
    """Kick off a full Apify scrape + AI review cycle (fire-and-forget)."""
    state = get_scraper_state()

    if state["running"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A scrape cycle is already running.",
        )

    if not settings.APIFY_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="APIFY API key is not configured.",
            headers={"X-Error-Code": CRV_6001},
        )

    actor_ids = [a for a in settings.APIFY_ACTOR_IDS if a.strip()]
    if not actor_ids:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No APIFY actor IDs configured. Set APIFY_ACTOR_IDS in .env.",
            headers={"X-Error-Code": CRV_6002},
        )

    start_urls = [u for u in settings.APIFY_START_URLS if u.strip()]
    if not start_urls:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No Facebook group URLs configured. Set APIFY_START_URLS in .env.",
            headers={"X-Error-Code": CRV_6002},
        )

    asyncio.create_task(run_scrape_once(force=True))
    metrics.increment("scraper_triggers")
    log.info("Scrape cycle manually triggered by admin")
    return {"ok": True, "message": "Scrape cycle triggered."}


@router.post("/trigger-web", status_code=status.HTTP_202_ACCEPTED)
@_limiter.limit("10/minute")
async def trigger_web_scrape(request: Request):
    """Kick off all enabled web scrapers (Dockwalk, Yotspot, Faststream, etc.) — no Apify cost."""
    state = get_scraper_state()
    if state["running"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A scrape cycle is already running.",
        )
    asyncio.create_task(run_scrape_once(force=True, web_only=True))
    metrics.increment("scraper_triggers")
    log.info("Web-only scrape manually triggered by admin")
    return {"ok": True, "message": "Web scrape started."}


# ── Manual import ─────────────────────────────────────────────────────────────

class ImportJobRequest(APIModel):
    text: Annotated[str, Field(min_length=10, max_length=5000, description="Raw job post text to review")]
    url: Annotated[str, Field(default="", max_length=260, description="Source URL (optional)")] = ""

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
_MAX_IMPORT_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB


def _run_import_pipeline(*, text: str, url: str, source: str = "manual"):
    from app.models import Job
    from app.services.ai_job_reviewer import review_post
    from app.services.job_sync import _build_job_fields, _content_hash, _job_fingerprint

    ai_fields = review_post(
        post_text=text,
        post_url=url,
        api_key=settings.OPENAI_API_KEY,
        model=settings.OPENAI_MODEL,
    )
    if ai_fields is None:
        return None

    fields = _build_job_fields(ai_fields, {"url": url, "text": text}, "manual")
    fields["source"] = source

    h = _content_hash(text) if text else None
    fields["content_hash"] = h
    fp = _job_fingerprint(
        fields.get("role"),
        fields.get("location"),
        fields.get("start_date"),
    )
    fields["job_fingerprint"] = fp

    db = SessionLocal()
    try:
        if h:
            exists = db.query(Job.id).filter(Job.content_hash == h).first()
            if exists:
                return {"duplicate": True, "id": exists[0]}
        if fp:
            exists = db.query(Job.id).filter(Job.job_fingerprint == fp).first()
            if exists:
                return {"duplicate": True, "id": exists[0]}

        if fields.get("application_url"):
            exists = db.query(Job.id).filter(
                Job.application_url == fields["application_url"]
            ).first()
            if exists:
                return {"duplicate": True, "id": exists[0]}

        job = Job(**fields)
        db.add(job)
        db.commit()
        db.refresh(job)
        return job
    finally:
        db.close()


def _shape_import_response(result):
    return {
        "ok": True,
        "id": result.id,
        "title": result.title,
        "role": result.role,
        "location": result.location,
        "source": result.source,
    }


@router.post("/import", status_code=status.HTTP_201_CREATED)
@_limiter.limit("20/minute")
async def import_job(request: Request, payload: ImportJobRequest):
    """
    Submit raw post text to the AI reviewer.
    If the AI confirms it is a job posting, it is saved to the database and returned.
    Returns 422 if the AI determines it is not a job posting.
    """
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured.",
        )

    result = await asyncio.to_thread(
        _run_import_pipeline,
        text=payload.text,
        url=payload.url,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The AI determined this is not a job posting. No record was created.",
        )

    if isinstance(result, dict) and result.get("duplicate"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A job with this URL already exists (id={result['id']}).",
        )

    log.info("Manual import succeeded | id=%d | title=%r", result.id, result.title)
    metrics.increment("manual_job_imports")
    return _shape_import_response(result)


def _save_job_from_ai_fields(*, ai_fields: dict, url: str, source: str = "manual_screenshot"):
    """Build Job row from AI-extracted fields and save to DB (dedup-aware)."""
    from app.models import Job
    from app.services.job_sync import _build_job_fields, _job_fingerprint

    fields = _build_job_fields(ai_fields, {"url": url}, "manual")
    fields["source"] = source
    fp = _job_fingerprint(
        fields.get("role"),
        fields.get("location"),
        fields.get("start_date"),
    )
    fields["job_fingerprint"] = fp

    db = SessionLocal()
    try:
        if fp:
            exists = db.query(Job.id).filter(Job.job_fingerprint == fp).first()
            if exists:
                return {"duplicate": True, "id": exists[0]}
        if fields.get("application_url"):
            exists = db.query(Job.id).filter(
                Job.application_url == fields["application_url"]
            ).first()
            if exists:
                return {"duplicate": True, "id": exists[0]}

        job = Job(**fields)
        db.add(job)
        db.commit()
        db.refresh(job)
        return job
    finally:
        db.close()


@router.post("/import-image", status_code=status.HTTP_201_CREATED)
@_limiter.limit("20/minute")
async def import_job_image(
    request: Request,
    file: UploadFile = File(...),
    url: str = Form(""),
):
    """AI reads a screenshot directly and extracts structured job fields in one pass."""
    import json as _json

    from app.services.ai_client import review_job_image
    from app.services.ai_job_reviewer import _SYSTEM_PROMPT

    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured.",
        )

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported image file extension.",
        )
    if file.content_type and file.content_type not in _IMAGE_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported image MIME type.",
        )

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty image upload.")
    if len(contents) > _MAX_IMPORT_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image exceeds 8 MB limit.",
        )

    raw_json = await asyncio.to_thread(
        review_job_image,
        api_key=settings.OPENAI_API_KEY,
        image_bytes=contents,
        mime_type=file.content_type or "image/png",
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

    result = await asyncio.to_thread(
        _save_job_from_ai_fields,
        ai_fields=parsed,
        url=url.strip(),
        source="manual_screenshot",
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not save the job. No record was created.",
        )
    if isinstance(result, dict) and result.get("duplicate"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A job with this content already exists (id={result['id']}).",
        )

    log.info("Screenshot import succeeded | id=%d | title=%r", result.id, result.title)
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
    }
