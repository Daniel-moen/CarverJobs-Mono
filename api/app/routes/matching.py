from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app import flags, metrics, schemas
from app.database import get_db
from app.logger import get_logger
from app.models import CrewProfile, Job, JobHistoryEntry, User
from app.security import require_admin_session
from app.services.matching_engine import (
    CandidateProfile,
    JobSummary,
    match_candidate_to_jobs,
)
from app.settings import settings

_limiter = Limiter(key_func=get_remote_address)
log = get_logger("carver.matching")

router = APIRouter(prefix="/matching", tags=["matching"], dependencies=[Depends(require_admin_session)])


def _user_to_candidate(user: User, profile: CrewProfile | None = None, job_history: list[JobHistoryEntry] | None = None) -> CandidateProfile:
    """Build a CandidateProfile from a User row, optionally enriched with CrewProfile data."""
    certs: list[str] = []
    langs: list[str] = []
    history: list[dict[str, str]] = []
    bio = ""

    if profile:
        if profile.certifications:
            certs = [c.strip() for c in profile.certifications.replace("\n", ",").split(",") if c.strip()]
        if profile.languages:
            langs = [lang.strip() for lang in profile.languages.split(",") if lang.strip()]
        bio = profile.bio or ""

    if job_history:
        for e in job_history:
            history.append({
                "role": e.role,
                "yacht": e.yacht_name,
                "yacht_type": e.yacht_type or "",
                "start_date": e.start_date or "",
                "end_date": e.end_date or "",
                "description": (e.description or "")[:200],
            })

    return CandidateProfile(
        user_key=str(user.id),
        first_name=profile.first_name or "" if profile else user.full_name.split()[0] if user.full_name else "",
        last_name=profile.last_name or "" if profile else " ".join(user.full_name.split()[1:]) if user.full_name else "",
        sex=profile.sex or "" if profile else "",
        desired_role=profile.desired_role or user.role or "" if profile else user.role or "",
        location=profile.current_location or user.current_location or "" if profile else user.current_location or "",
        preferred_locations=profile.preferred_locations or "" if profile else "",
        nationality=profile.nationality or user.nationality or "" if profile else user.nationality or "",
        years_experience=profile.years_experience or str(user.years_experience or "") if profile else str(user.years_experience or ""),
        salary_min=profile.salary_min or "" if profile else "",
        salary_max=profile.salary_max or "" if profile else "",
        contract_type=profile.contract_type or "" if profile else "",
        rotation_preference=profile.rotation_preference or "" if profile else "",
        available_from=profile.available_from or "" if profile else "",
        certifications=certs,
        languages=langs,
        bio=bio,
        job_history=history,
    )


def _job_to_summary(j: Job) -> JobSummary:
    return JobSummary(
        job_id=j.id,
        title=j.title,
        role=j.role or "",
        department=j.department or "",
        location=j.location,
        yacht_type=j.yacht_type or "",
        yacht_length_m=j.yacht_length_m,
        start_date=j.start_date or "",
        contract_type=j.contract_type or "",
        rotation=j.rotation or "",
        season=j.season or "",
        salary_min=j.salary_min,
        salary_max=j.salary_max,
        salary_currency=j.salary_currency or "EUR",
        experience_required_years=j.experience_required_years,
        certifications_required=j.certifications_required or "",
        languages_required=j.languages_required or "",
        description=j.description or "",
    )


@router.post("/run", response_model=schemas.MatchingRunResponse)
@_limiter.limit("10/minute")
async def run_match(request: Request, payload: schemas.MatchingRequest, db: Session = Depends(get_db)):
    if not flags.is_enabled("matching"):
        metrics.increment("feature_blocked")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Job matching is temporarily disabled.")

    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Matching not configured (missing API key).")

    log.info("Run request | user_id=%d | job_statuses=%s", payload.user_id, payload.job_statuses)

    user = db.query(User).filter(User.id == payload.user_id, User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    all_jobs = (
        db.query(Job)
        .filter(Job.status.in_(payload.job_statuses))
        .order_by(Job.created_at.desc())
        .all()
    )
    if not all_jobs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No jobs found")

    profile = db.query(CrewProfile).filter(CrewProfile.user_key == str(user.id)).first()
    job_history = None
    if profile:
        job_history = (
            db.query(JobHistoryEntry)
            .filter(JobHistoryEntry.user_key == str(user.id))
            .order_by(JobHistoryEntry.start_date.desc())
            .limit(10)
            .all()
        )

    candidate = _user_to_candidate(user, profile, job_history)
    job_summaries = [_job_to_summary(j) for j in all_jobs]

    log.info("Running match | user_id=%d | jobs=%d", payload.user_id, len(all_jobs))
    t0 = time.perf_counter()

    try:
        results = await asyncio.to_thread(
            match_candidate_to_jobs,
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_MODEL,
            candidate=candidate,
            jobs=job_summaries,
        )
    except Exception as exc:
        log.error("Match engine error | user_id=%d | %s", payload.user_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Matching failed. Please try again.")
    finally:
        metrics.record_ai_response_time(round((time.perf_counter() - t0) * 1000))

    metrics.increment("matching_completed")
    log.info("Match complete | user_id=%d | results=%d | matched=%d",
             payload.user_id, len(results), sum(1 for r in results if r.matched))

    return schemas.MatchingRunResponse(
        request_id=f"match-{payload.user_id}-{int(time.time())}",
        matches=[
            schemas.MatchResultItem(
                job_id=str(r.job_id),
                matched=r.matched,
                compatibility=r.compatibility,
                reason=r.reason,
                strengths=r.strengths,
                gaps=r.gaps,
                factor_scores=r.factor_scores,
            )
            for r in results
        ],
    )
