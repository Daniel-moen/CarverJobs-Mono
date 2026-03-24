import asyncio
import json
import queue
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app import metrics
from app.database import get_db
from app.logger import get_logger
from app.models import CrewProfile, Job, JobHistoryEntry, MatchSession, MatchSessionResult
from app.schemas import (
    CrewMatchJob,
    CrewMatchV2Response,
    DraftEmailRequest,
    DraftEmailResponse,
    MatchSessionDetail,
    MatchSessionListResponse,
    MatchSessionResultItem,
    MatchSessionSummary,
)
from app.security import require_session
from app.services.ai_client import AIClientError, call_openai
from app.services.matching_v2 import (
    CandidateProfile,
    JobSummary,
    match_candidate_to_jobs,
)
from app.settings import settings

log = get_logger("carver.crew_match")
_limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/matching", tags=["crew-matching"])


# ── Mapping helpers ──────────────────────────────────────────────────────────

def _profile_to_candidate(
    p: CrewProfile,
    job_history: list[JobHistoryEntry] | None = None,
) -> CandidateProfile:
    certs: list[str] = []
    if p.certifications:
        certs = [c.strip() for c in p.certifications.replace("\n", ",").split(",") if c.strip()]

    langs: list[str] = []
    if p.languages:
        langs = [lang.strip() for lang in p.languages.split(",") if lang.strip()]

    history: list[dict[str, str]] = []
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
        user_key=p.user_key,
        first_name=p.first_name or "",
        last_name=p.last_name or "",
        sex=p.sex or "",
        desired_role=p.desired_role or "",
        location=p.current_location or "",
        preferred_locations=p.preferred_locations or "",
        nationality=p.nationality or "",
        years_experience=p.years_experience or "",
        salary_min=p.salary_min or "",
        salary_max=p.salary_max or "",
        contract_type=p.contract_type or "",
        rotation_preference=p.rotation_preference or "",
        available_from=p.available_from or "",
        certifications=certs,
        languages=langs,
        bio=p.bio or "",
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


def _job_to_schema(j: Job) -> CrewMatchJob:
    return CrewMatchJob(
        id=j.id,
        title=j.title,
        role=j.role,
        yacht=j.yacht,
        location=j.location,
        contract_type=j.contract_type,
        salary_min=j.salary_min,
        salary_max=j.salary_max,
        salary_currency=j.salary_currency,
        contact_email=j.contact_email,
        description=j.description,
        yacht_type=j.yacht_type,
        yacht_length_m=j.yacht_length_m,
        start_date=j.start_date,
        season=j.season,
        rotation=j.rotation,
        experience_required_years=j.experience_required_years,
        certifications_required=j.certifications_required,
        languages_required=j.languages_required,
        requirements=j.requirements,
        responsibilities=j.responsibilities,
        benefits=j.benefits,
        recruiter_name=j.recruiter_name,
        recruiter_agency=j.recruiter_agency,
        application_url=j.application_url,
        urgent_hire=j.urgent_hire,
        source=j.source,
    )


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

@router.post("/find")
@_limiter.limit("5/minute")
async def find_match(
    request: Request,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Run a full match session with live progress via Server-Sent Events.

    Streams events:
      event: progress  — after each batch: {jobs_scanned, total_jobs, matches_so_far, batch}
      event: complete   — final result: full CrewMatchV2Response JSON
      event: error      — on failure: {detail: "..."}
    """

    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="Matching not configured (missing API key).")

    user_key = session["sub"]
    profile = db.query(CrewProfile).filter(CrewProfile.user_key == user_key).first()
    if not profile:
        raise HTTPException(status_code=400, detail="Save your profile first before matching.")

    all_jobs = (
        db.query(Job)
        .filter(Job.status.in_(["open", "priority"]))
        .order_by(Job.created_at.desc())
        .all()
    )
    if not all_jobs:
        async def empty_stream():
            data = json.dumps({"session_id": 0, "matched": False, "total_jobs_scanned": 0, "total_matched": 0, "matches": []})
            yield f"event: complete\ndata: {data}\n\n"
        return StreamingResponse(empty_stream(), media_type="text/event-stream")

    match_session = MatchSession(user_key=user_key, status="running", total_jobs_scanned=len(all_jobs))
    db.add(match_session)
    db.commit()
    db.refresh(match_session)
    session_id = match_session.id

    job_history = (
        db.query(JobHistoryEntry)
        .filter(JobHistoryEntry.user_key == user_key)
        .order_by(JobHistoryEntry.start_date.desc())
        .limit(10)
        .all()
    )

    candidate = _profile_to_candidate(profile, job_history)
    job_summaries = [_job_to_summary(j) for j in all_jobs]
    jobs_by_id = {j.id: j for j in all_jobs}

    log.info("Match session %d | user=%s | jobs=%d", session_id, user_key, len(all_jobs))

    progress_queue: queue.Queue[dict] = queue.Queue()

    def on_progress(jobs_scanned: int, total_jobs: int, matches_so_far: int, batch_num: int, total_batches: int):
        progress_queue.put({
            "jobs_scanned": jobs_scanned,
            "total_jobs": total_jobs,
            "matches_so_far": matches_so_far,
            "batch": batch_num,
            "total_batches": total_batches,
        })

    async def event_stream():
        t0 = time.perf_counter()

        match_task = asyncio.get_event_loop().run_in_executor(
            None,
            lambda: match_candidate_to_jobs(
                api_key=settings.OPENAI_API_KEY,
                model=settings.OPENAI_MODEL,
                candidate=candidate,
                jobs=job_summaries,
                on_progress=on_progress,
            ),
        )

        from app.services.matching_v2 import BATCH_SIZE
        _total_batches = (len(all_jobs) + BATCH_SIZE - 1) // BATCH_SIZE
        yield f"event: progress\ndata: {json.dumps({'jobs_scanned': 0, 'total_jobs': len(all_jobs), 'matches_so_far': 0, 'batch': 0, 'total_batches': _total_batches})}\n\n"

        last_ping = time.perf_counter()
        while not match_task.done():
            await asyncio.sleep(0.5)
            sent_something = False
            while not progress_queue.empty():
                try:
                    evt = progress_queue.get_nowait()
                    yield f"event: progress\ndata: {json.dumps(evt)}\n\n"
                    sent_something = True
                    last_ping = time.perf_counter()
                except queue.Empty:
                    break
            if not sent_something and (time.perf_counter() - last_ping) > 8:
                yield ": keepalive\n\n"
                last_ping = time.perf_counter()

        try:
            results = match_task.result()
        except Exception as exc:
            match_session.status = "failed"
            db.commit()
            log.error("Match session %d failed | user=%s | %s", session_id, user_key, exc)
            yield f"event: error\ndata: {json.dumps({'detail': 'Matching failed. Please try again.'})}\n\n"
            return
        finally:
            metrics.record_ai_response_time(round((time.perf_counter() - t0) * 1000))

        while not progress_queue.empty():
            try:
                evt = progress_queue.get_nowait()
                yield f"event: progress\ndata: {json.dumps(evt)}\n\n"
            except queue.Empty:
                break

        matched_results = [r for r in results if r.matched]

        for r in results:
            if r.matched:
                db.add(MatchSessionResult(
                    session_id=session_id,
                    job_id=r.job_id,
                    matched=r.matched,
                    compatibility=r.compatibility,
                    reason=r.reason,
                    strengths=json.dumps(r.strengths),
                    gaps=json.dumps(r.gaps),
                    factor_scores=json.dumps(r.factor_scores),
                ))

        match_session.status = "completed"
        match_session.total_matched = len(matched_results)
        match_session.completed_at = datetime.now(timezone.utc)
        db.commit()

        response_matches = []
        for r in matched_results:
            db_job = jobs_by_id.get(r.job_id)
            if not db_job:
                continue
            response_matches.append(MatchSessionResultItem(
                job=_job_to_schema(db_job),
                matched=r.matched,
                compatibility=r.compatibility,
                reason=r.reason,
                strengths=r.strengths,
                gaps=r.gaps,
                factor_scores=r.factor_scores,
            ))

        metrics.increment("crew_matches")
        log.info("Match session %d complete | user=%s | scanned=%d | matched=%d",
                 session_id, user_key, len(all_jobs), len(matched_results))

        final = CrewMatchV2Response(
            session_id=session_id,
            matched=len(response_matches) > 0,
            total_jobs_scanned=len(all_jobs),
            total_matched=len(matched_results),
            matches=response_matches,
        )
        yield f"event: complete\ndata: {final.model_dump_json()}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/sessions", response_model=MatchSessionListResponse)
@_limiter.limit("20/minute")
async def list_sessions(
    request: Request,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """List all past match sessions for the current user, newest first."""
    user_key = session["sub"]
    sessions = (
        db.query(MatchSession)
        .filter(MatchSession.user_key == user_key)
        .order_by(MatchSession.created_at.desc())
        .limit(50)
        .all()
    )
    return MatchSessionListResponse(
        sessions=[MatchSessionSummary.model_validate(s) for s in sessions]
    )


@router.get("/sessions/{session_id}", response_model=MatchSessionDetail)
@_limiter.limit("20/minute")
async def get_session(
    session_id: int,
    request: Request,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    """Get full results for a specific match session. Only the session owner can view it."""
    user_key = session["sub"]
    match_session = (
        db.query(MatchSession)
        .filter(MatchSession.id == session_id, MatchSession.user_key == user_key)
        .first()
    )
    if not match_session:
        raise HTTPException(status_code=404, detail="Session not found.")

    stored_results = (
        db.query(MatchSessionResult)
        .filter(MatchSessionResult.session_id == session_id)
        .all()
    )

    job_ids = [r.job_id for r in stored_results]
    jobs_map: dict[int, Job] = {}
    if job_ids:
        jobs = db.query(Job).filter(Job.id.in_(job_ids)).all()
        jobs_map = {j.id: j for j in jobs}

    result_items: list[MatchSessionResultItem] = []
    for r in stored_results:
        db_job = jobs_map.get(r.job_id)
        if not db_job:
            continue

        strengths = []
        gaps = []
        factor_scores = {}
        try:
            strengths = json.loads(r.strengths) if r.strengths else []
        except json.JSONDecodeError:
            pass
        try:
            gaps = json.loads(r.gaps) if r.gaps else []
        except json.JSONDecodeError:
            pass
        try:
            factor_scores = json.loads(r.factor_scores) if r.factor_scores else {}
        except json.JSONDecodeError:
            pass

        result_items.append(MatchSessionResultItem(
            job=_job_to_schema(db_job),
            matched=r.matched,
            compatibility=r.compatibility,
            reason=r.reason or "",
            strengths=strengths,
            gaps=gaps,
            factor_scores=factor_scores,
        ))

    result_items.sort(key=lambda x: x.compatibility, reverse=True)

    return MatchSessionDetail(
        id=match_session.id,
        status=match_session.status,
        total_jobs_scanned=match_session.total_jobs_scanned,
        total_matched=match_session.total_matched,
        created_at=match_session.created_at,
        completed_at=match_session.completed_at,
        results=result_items,
    )


# ── Draft email (unchanged) ─────────────────────────────────────────────────

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
