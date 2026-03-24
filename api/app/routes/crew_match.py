import asyncio
import json
import time
from pathlib import Path
import sys
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app import metrics
from app.database import get_db
from app.logger import get_logger
from app.models import CrewProfile, Job, JobHistoryEntry
from app.schemas import CrewMatchAI, CrewMatchItem, CrewMatchJob, CrewMatchResponse, DraftEmailRequest, DraftEmailResponse
from app.security import require_session
from app.services.ai_client import AIClientError, call_openai
from app.settings import settings

log = get_logger("carver.crew_match")
_limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/matching", tags=["crew-matching"])

# ── Import the real Matching Engine ──────────────────────────────────────────
ENGINE_DIR = Path(__file__).resolve().parents[2] / "Matching Engine"
_ENGINE_OK = False

if ENGINE_DIR.exists() and ENGINE_DIR.is_dir():
    if str(ENGINE_DIR) not in sys.path:
        sys.path.insert(0, str(ENGINE_DIR))
    try:
        from models.job import JobPosting
        from models.user import UserProfile
        from services.matching_service import MatchingService
        from services.openai_client import OpenAIClient
        from services.prompt_builder import PromptBuilder
        from utils.batching import FixedSizeBatchStrategy

        _ENGINE_OK = True
        log.info("Matching Engine loaded from %s", ENGINE_DIR)
    except Exception as exc:
        log.warning("Could not import Matching Engine: %s", exc)


def _build_matching_service() -> Optional[MatchingService]:
    if not _ENGINE_OK or not settings.OPENAI_API_KEY:
        return None
    return MatchingService(
        llm_client=OpenAIClient(api_key=settings.OPENAI_API_KEY, model=settings.OPENAI_MODEL),
        batch_strategy=FixedSizeBatchStrategy(batch_size=5),
        prompt_builder=PromptBuilder(),
        verbose=False,
    )


_service_instance: Optional[MatchingService] = None


def _get_service() -> Optional[MatchingService]:
    global _service_instance
    if _service_instance is None:
        _service_instance = _build_matching_service()
    return _service_instance


# ── Mapping helpers ──────────────────────────────────────────────────────────

def _crew_to_user_profile(p: CrewProfile, job_history: list[JobHistoryEntry] | None = None) -> UserProfile:
    """Map a CrewProfile DB row to the Matching Engine's UserProfile."""
    pay_min = 0.0
    if p.salary_min:
        try:
            pay_min = float(p.salary_min)
        except (ValueError, TypeError):
            pass

    pay_max = 0.0
    if p.salary_max:
        try:
            pay_max = float(p.salary_max)
        except (ValueError, TypeError):
            pass

    yrs = 0.0
    if p.years_experience:
        try:
            yrs = float(p.years_experience)
        except (ValueError, TypeError):
            pass

    certs = []
    if p.certifications:
        certs = [c.strip() for c in p.certifications.replace("\n", ",").split(",") if c.strip()]

    languages = []
    if p.languages:
        languages = [l.strip() for l in p.languages.split(",") if l.strip()]

    history = []
    if job_history:
        for entry in job_history:
            history.append({
                "role": entry.role,
                "yacht": entry.yacht_name,
                "yacht_type": entry.yacht_type or "",
                "start_date": entry.start_date or "",
                "end_date": entry.end_date or "",
                "description": (entry.description or "")[:200],
            })

    return UserProfile(
        user_id=p.user_key,
        desired_role=p.desired_role or "",
        location=p.preferred_locations or p.current_location or "Unknown",
        desired_pay_min=pay_min,
        desired_length=p.contract_type or "Any",
        skills=[],
        certifications=certs,
        years_experience=yrs,
        languages=languages,
        nationality=p.nationality or "",
        rotation_preference=p.rotation_preference or "",
        available_from=p.available_from or "",
        salary_max=pay_max,
        bio=(p.bio or "")[:400],
        job_history=history,
    )


def _job_to_posting(j: Job) -> JobPosting:
    """Map a Job DB row to the Matching Engine's JobPosting."""
    pay = float(j.salary_max or j.salary_min or 0.0)
    skills = []
    if j.requirements:
        skills = [s.strip() for s in j.requirements[:300].replace("\n", ",").split(",") if s.strip()]
    certs = []
    if j.certifications_required:
        certs = [c.strip() for c in j.certifications_required.replace("\n", ",").split(",") if c.strip()]
    return JobPosting(
        job_id=str(j.id),
        title=j.title,
        role=j.role or "",
        location=j.location,
        pay=pay,
        length=j.contract_type or "Unknown",
        description=j.description or "",
        required_skills=skills,
        preferred_certifications=certs,
    )


_DEPT_MAP: dict[str, str] = {}
for _dept, _roles in {
    "deck": ["deckhand", "bosun", "lead deckhand", "deck/stew", "mate", "first mate", "officer", "deck officer", "first officer", "second officer"],
    "interior": ["stewardess", "stew", "chief stew", "chief stewardess", "head of interior", "head stew", "2nd stew", "3rd stew", "junior stew", "service stewardess", "interior", "housekeeper", "laundry"],
    "bridge": ["captain", "master", "relief captain"],
    "engine": ["engineer", "eto", "electro-technical officer", "chief engineer", "2nd engineer", "3rd engineer", "lead engineer", "oiler", "wiper"],
    "galley": ["chef", "head chef", "sous chef", "cook", "galley", "pastry chef", "crew chef"],
    "medical": ["medic", "nurse", "paramedic"],
    "pursers": ["purser", "administrator", "admin"],
}.items():
    for _r in _roles:
        _DEPT_MAP[_r] = _dept
    _DEPT_MAP[_dept] = _dept


def _role_department(role_text: str) -> str | None:
    """Map a role string to a yacht department via keyword lookup."""
    lower = role_text.lower().strip()
    if lower in _DEPT_MAP:
        return _DEPT_MAP[lower]
    for key, dept in _DEPT_MAP.items():
        if key in lower:
            return dept
    return None


def _role_prefilter(jobs: list[Job], desired_role: str, limit: int = 20) -> list[Job]:
    """Pre-filter jobs by department + keyword relevance before the LLM.

    Prioritises same-department jobs, then ranks by keyword overlap.
    Falls back to all jobs (sorted by keyword score) if too few match.
    """
    if not desired_role:
        return jobs[:limit]

    desired_dept = _role_department(desired_role)
    keywords = set(desired_role.lower().split())

    def score(job: Job) -> tuple[int, int]:
        role_text = (job.role or "").lower()
        dept_match = 1 if desired_dept and _role_department(role_text) == desired_dept else 0
        kw_match = len(keywords & set(role_text.split()))
        return (dept_match, kw_match)

    scored = sorted(jobs, key=score, reverse=True)
    dept_hits = [j for j in scored if score(j)[0] > 0]
    return (dept_hits if len(dept_hits) >= 3 else scored)[:limit]


def _profile_summary(p: CrewProfile) -> str:
    parts = []
    if p.desired_role:
        parts.append(f"Desired role: {p.desired_role}")
    if p.years_experience:
        parts.append(f"Experience: {p.years_experience} years")
    if p.certifications:
        parts.append(f"Certifications: {p.certifications}")
    if p.languages:
        parts.append(f"Languages: {p.languages}")
    if p.preferred_locations:
        parts.append(f"Preferred locations: {p.preferred_locations}")
    if p.contract_type:
        parts.append(f"Contract preference: {p.contract_type}")
    if p.current_location:
        parts.append(f"Current location: {p.current_location}")
    if p.nationality:
        parts.append(f"Nationality: {p.nationality}")
    if p.salary_min or p.salary_max:
        parts.append(f"Salary range: {p.salary_min or '?'}-{p.salary_max or '?'} EUR/mo")
    if p.bio:
        parts.append(f"Bio: {p.bio[:300]}")
    return "\n".join(parts) if parts else "No profile details available."


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/find", response_model=CrewMatchResponse)
@_limiter.limit("5/minute")
async def find_match(
    request: Request,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="Matching is not configured (missing API key).")

    user_key = session["sub"]
    profile = db.query(CrewProfile).filter(CrewProfile.user_key == user_key).first()
    if not profile:
        raise HTTPException(status_code=400, detail="Save your profile first before matching.")

    all_jobs = db.query(Job).filter(Job.status.in_(["open", "priority"])).order_by(Job.created_at.desc()).limit(100).all()

    if not all_jobs:
        return CrewMatchResponse(matched=False)

    jobs = _role_prefilter(all_jobs, profile.desired_role or "", limit=30)
    jobs_by_id = {str(j.id): j for j in jobs}

    service = _get_service()
    if service is None:
        log.warning("Matching Engine unavailable, cannot match for user=%s", user_key)
        raise HTTPException(status_code=503, detail="Matching engine is not available.")

    job_history = db.query(JobHistoryEntry).filter(JobHistoryEntry.user_key == user_key).order_by(JobHistoryEntry.start_date.desc()).limit(10).all()
    user_profile = _crew_to_user_profile(profile, job_history)
    job_postings = [_job_to_posting(j) for j in jobs]

    t0 = time.perf_counter()
    try:
        results = await asyncio.to_thread(service.match_user_to_jobs, user_profile, job_postings)
    except Exception as exc:
        log.error("Matching Engine error | user=%s | %s", user_key, exc)
        raise HTTPException(status_code=502, detail="Matching failed. Please try again.")
    finally:
        metrics.record_ai_response_time(round((time.perf_counter() - t0) * 1000))

    if not results:
        log.info("Matching Engine returned no results | user=%s", user_key)
        return CrewMatchResponse(matched=False)

    for r in results:
        log.info("Match result | user=%s | job_id=%s | matched=%s | compat=%.0f | reason=%s",
                 user_key, r.job_id, r.matched, r.compatibility, r.reason[:120])

    def _build_item(match, db_job) -> CrewMatchItem:
        return CrewMatchItem(
            job=CrewMatchJob(
                id=db_job.id,
                title=db_job.title,
                role=db_job.role,
                yacht=db_job.yacht,
                location=db_job.location,
                contract_type=db_job.contract_type,
                salary_min=db_job.salary_min,
                salary_max=db_job.salary_max,
                salary_currency=db_job.salary_currency,
                contact_email=db_job.contact_email,
                description=db_job.description,
                yacht_type=db_job.yacht_type,
                yacht_length_m=db_job.yacht_length_m,
                start_date=db_job.start_date,
                season=db_job.season,
                rotation=db_job.rotation,
                experience_required_years=db_job.experience_required_years,
                certifications_required=db_job.certifications_required,
                languages_required=db_job.languages_required,
                requirements=db_job.requirements,
                responsibilities=db_job.responsibilities,
                benefits=db_job.benefits,
                recruiter_name=db_job.recruiter_name,
                recruiter_agency=db_job.recruiter_agency,
                application_url=db_job.application_url,
                urgent_hire=db_job.urgent_hire,
                source=db_job.source,
            ),
            ai=CrewMatchAI(
                reason=match.reason,
                compatibility=match.compatibility,
                strengths=match.strengths,
                gaps=match.gaps,
            ),
        )

    strong_items: list[CrewMatchItem] = []
    near_items: list[CrewMatchItem] = []
    for match in results:
        db_job = jobs_by_id.get(match.job_id)
        if not db_job:
            continue
        item = _build_item(match, db_job)
        if match.matched:
            strong_items.append(item)
        elif match.compatibility >= 30:
            near_items.append(item)

    matched_items = strong_items if strong_items else near_items[:5]

    if not matched_items:
        log.info("No matched jobs from engine | user=%s | results=%d", user_key, len(results))
        return CrewMatchResponse(matched=False)

    metrics.increment("crew_matches")
    log.info("Crew match complete | user=%s | matches=%d | top_job=%s | top_compat=%.0f",
             user_key, len(matched_items), matched_items[0].job.id, matched_items[0].ai.compatibility)

    return CrewMatchResponse(matched=True, matches=matched_items)


@router.post("/draft-email", response_model=DraftEmailResponse)
@_limiter.limit("10/minute")
async def draft_email(
    request: Request,
    payload: DraftEmailRequest = Body(...),
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="AI drafting not configured.")

    user_key = session["sub"]
    profile = db.query(CrewProfile).filter(CrewProfile.user_key == user_key).first()
    if not profile:
        raise HTTPException(status_code=400, detail="Save your profile first.")

    job = db.query(Job).filter(Job.id == payload.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    profile_url = ""
    if profile.profile_slug:
        profile_url = f"https://carver.app/crew/{profile.profile_slug}"

    name = " ".join(filter(None, [profile.first_name, profile.last_name])) or "the applicant"

    system_prompt = f"""You are a professional yacht crew career assistant.
Draft a short, polite application email from {name} for the position below.
Keep it under 120 words. Be warm but professional — no fluff.
Mention relevant experience/qualifications from their profile where they match the job.
End with a sign-off using their first name only.

Crew profile:
{_profile_summary(profile)}

Job details:
Role: {job.role}
Yacht: {job.yacht}
Location: {job.location}
Contract: {job.contract_type or 'Not specified'}
Description: {(job.description or '')[:400]}
Requirements: {(job.requirements or '')[:300]}
{"Profile link: " + profile_url if profile_url else ""}

Return strict JSON only:
{{"subject": "<email subject line>", "body": "<email body text>"}}"""

    t0 = time.perf_counter()
    try:
        text = await asyncio.to_thread(
            call_openai,
            api_key=settings.OPENAI_API_KEY,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Draft the application email."},
            ],
            model=settings.OPENAI_MODEL,
            max_tokens=400,
            temperature=0.7,
            response_format={"type": "json_object"},
        )
    except AIClientError as exc:
        log.error("AI error drafting email | code=%s | error=%s", exc.crv_code, exc)
        raise HTTPException(status_code=502, detail="Could not draft email. Try again.")
    except Exception as exc:
        log.error("Unexpected error drafting email | error=%s", exc)
        raise HTTPException(status_code=502, detail="Drafting service error.")
    finally:
        metrics.record_ai_response_time(round((time.perf_counter() - t0) * 1000))

    log.info("Draft email raw response | %s", text[:300])

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Could not parse draft.")

    return DraftEmailResponse(
        to=job.contact_email or "",
        subject=str(parsed.get("subject", f"Application: {job.role} – {job.yacht}")),
        body=str(parsed.get("body", "")),
    )
