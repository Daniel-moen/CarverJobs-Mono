"""
Admin routes for scraper management.

  GET  /scraper/status        — APIFY scheduler state + last run result
  POST /scraper/trigger       — kick off a full Apify scrape + AI review cycle
  POST /scraper/import        — submit raw post text to AI review and save if valid
"""
import asyncio
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app import metrics
from app.database import SessionLocal
from app.error_codes import CRV_6001, CRV_6002
from app.logger import get_logger
from app.scheduler import get_scraper_state, run_scrape_once
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

class ImportJobRequest(BaseModel):
    text: Annotated[str, Field(min_length=10, max_length=5000, description="Raw job post text to review")]
    url: Annotated[str, Field(default="", max_length=260, description="Source URL (optional)")] = ""


@router.post("/import", status_code=status.HTTP_201_CREATED)
@_limiter.limit("20/minute")
async def import_job(request: Request, payload: ImportJobRequest):
    """
    Submit raw post text to the AI reviewer.
    If the AI confirms it is a job posting, it is saved to the database and returned.
    Returns 422 if the AI determines it is not a job posting.
    """
    from app.models import Job
    from app.services.ai_job_reviewer import review_post
    from app.services.job_sync import _build_job_fields

    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured.",
        )

    def _review_and_save():
        from app.services.job_sync import _content_hash

        ai_fields = review_post(
            post_text=payload.text,
            post_url=payload.url,
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_MODEL,
        )
        if ai_fields is None:
            return None

        fields = _build_job_fields(ai_fields, {"url": payload.url, "text": payload.text})
        fields["source"] = "manual"

        # Attach content hash
        h = _content_hash(payload.text) if payload.text else None
        fields["content_hash"] = h

        db = SessionLocal()
        try:
            # Dedup by content hash first
            if h:
                exists = db.query(Job.id).filter(Job.content_hash == h).first()
                if exists:
                    return {"duplicate": True, "id": exists[0]}

            # Secondary dedup by URL
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

    result = await asyncio.to_thread(_review_and_save)

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

    # Return a plain dict so we don't need a full schema dependency here
    return {
        "ok": True,
        "id": result.id,
        "title": result.title,
        "role": result.role,
        "location": result.location,
        "source": result.source,
    }
