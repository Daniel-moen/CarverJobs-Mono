"""
Crew-facing job submission — same AI review as admin ingest, earns 1 token on success.
"""
import asyncio
import json as _json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app import metrics
from app.database import get_db
from app.logger import get_logger
from app.security import require_crew_or_admin_session
from app.services.credits import add_credits
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

log = get_logger("carver.job_submit")
_limiter = Limiter(key_func=get_remote_address)

# Vision submit: several screenshots of one long listing (website); cap size/count for safety.
_MAX_SUBMIT_IMAGE_COUNT = 6
_MAX_SUBMIT_TOTAL_BYTES = 24 * 1024 * 1024

router = APIRouter(prefix="/jobs/submit", tags=["job-submit"])


@router.post("/text", status_code=status.HTTP_201_CREATED)
@_limiter.limit("10/minute")
async def crew_submit_text(
    request: Request,
    payload: ImportJobRequest,
    session: dict = Depends(require_crew_or_admin_session),
    db: Session = Depends(get_db),
):
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured.",
        )

    result = await asyncio.to_thread(
        _run_import_pipeline,
        text=payload.text,
        url=payload.url,
        source="website_submit",
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
    new_bal = add_credits(db, user_key, amount=1)
    log.info("Crew text job submit | id=%d | sub=%s…", result.id, (user_key or "")[:12])
    metrics.increment("manual_job_imports")

    out = _shape_import_response(result)
    out["credits_balance"] = new_bal
    return out


@router.post("/image", status_code=status.HTTP_201_CREATED)
@_limiter.limit("10/minute")
async def crew_submit_image(
    request: Request,
    url: str = Form(""),
    session: dict = Depends(require_crew_or_admin_session),
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

    result = await asyncio.to_thread(
        _save_job_from_ai_fields,
        ai_fields=parsed,
        url=url.strip(),
        source="website_submit_screenshot",
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
    new_bal = add_credits(db, user_key, amount=1)
    log.info("Crew image job submit | id=%d | sub=%s…", result.id, (user_key or "")[:12])
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
