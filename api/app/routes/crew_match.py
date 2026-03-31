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
from app.services.matching_engine import (
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


def _profile_summary(p: CrewProfile, job_history: list | None = None) -> str:
    parts = []
    if p.first_name or p.last_name:
        parts.append(f"Name: {' '.join(filter(None, [p.first_name, p.last_name]))}")
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
    if job_history:
        history_lines = []
        for e in job_history[:5]:
            line = f"  - {e.role} on {e.yacht_name}"
            if e.yacht_type:
                line += f" ({e.yacht_type})"
            if e.start_date or e.end_date:
                line += f" | {e.start_date or '?'} – {e.end_date or 'present'}"
            history_lines.append(line)
        parts.append("Work history:\n" + "\n".join(history_lines))
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
      event: progress  — after each batch: {jobs_scanned, total_jobs, matches_so_far, batch, total_batches}
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
    total_job_count = len(all_jobs)

    log.info("Match session %d | user=%s | jobs=%d", session_id, user_key, total_job_count)

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
        from app.database import SessionLocal
        from app.services.matching_engine import BATCH_SIZE

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

        _total_batches = (total_job_count + BATCH_SIZE - 1) // BATCH_SIZE
        yield f"event: progress\ndata: {json.dumps({'jobs_scanned': 0, 'total_jobs': total_job_count, 'matches_so_far': 0, 'batch': 0, 'total_batches': _total_batches})}\n\n"

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
            stream_db = SessionLocal()
            try:
                s = stream_db.query(MatchSession).get(session_id)
                if s:
                    s.status = "failed"
                    stream_db.commit()
            finally:
                stream_db.close()
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

        stream_db = SessionLocal()
        try:
            for r in matched_results:
                stream_db.add(MatchSessionResult(
                    session_id=session_id,
                    job_id=r.job_id,
                    matched=r.matched,
                    compatibility=r.compatibility,
                    reason=r.reason,
                    strengths=json.dumps(r.strengths),
                    gaps=json.dumps(r.gaps),
                    factor_scores=json.dumps(r.factor_scores),
                ))

            s = stream_db.query(MatchSession).get(session_id)
            if s:
                s.status = "completed"
                s.total_matched = len(matched_results)
                s.completed_at = datetime.now(timezone.utc)
            stream_db.commit()
        except Exception:
            log.exception("Failed to persist match session %d results", session_id)
            stream_db.rollback()
        finally:
            stream_db.close()

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
                 session_id, user_key, total_job_count, len(matched_results))

        final = CrewMatchV2Response(
            session_id=session_id,
            matched=len(response_matches) > 0,
            total_jobs_scanned=total_job_count,
            total_matched=len(matched_results),
            matches=response_matches,
        )
        yield f"event: complete\ndata: {final.model_dump_json()}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
        profile_url = f"{settings.FRONTEND_BASE_URL}/crew/{profile.profile_slug}"

    first_name = profile.first_name or "the applicant"

    job_history = (
        db.query(JobHistoryEntry)
        .filter(JobHistoryEntry.user_key == user_key)
        .order_by(JobHistoryEntry.start_date.desc())
        .limit(5)
        .all()
    )

    profile_text = _profile_summary(profile, job_history)

    system_prompt = f"""You write application emails for yacht crew members. Your output must sound like a real person wrote it — natural, confident, and conversational. Not robotic, not overly formal.

STRICT RULES:
- ONLY mention qualifications, certifications, experience, and facts that appear in the crew profile below. NEVER invent or assume anything.
- If the profile is sparse, keep the email shorter rather than making things up.
- Do NOT use clichés like "I am excited to" or "I believe I would be a great fit". Write like an experienced crew member who knows their worth.
- Keep it under 150 words. Short paragraphs. No bullet points.
- Include the profile link naturally (e.g. "You can view my full profile and documents here: [link]").
- Sign off with just the first name: {first_name}

Crew profile:
{profile_text}

Job:
Role: {job.role}
Yacht: {job.yacht}
Location: {job.location}
Contract: {job.contract_type or 'Not specified'}
{('Description: ' + (job.description or '')[:400]) if job.description else ''}
{('Requirements: ' + (job.requirements or '')[:300]) if job.requirements else ''}
{('Profile link: ' + profile_url) if profile_url else 'No profile link available.'}

Respond with JSON only. No markdown, no explanation:
{{"subject": "...", "body": "..."}}"""

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
    ]

    if payload.prompt and payload.previous_body:
        messages.append({"role": "assistant", "content": json.dumps({"subject": "", "body": payload.previous_body})})
        messages.append({"role": "user", "content": f"Revise the email with this instruction (keep the same strict rules — don't invent facts): {payload.prompt}"})
    elif payload.prompt:
        messages.append({"role": "user", "content": f"Write the email. Extra instruction: {payload.prompt}"})
    else:
        messages.append({"role": "user", "content": "Write the email."})

    t0 = time.perf_counter()
    text = ""
    for _attempt in range(2):
        try:
            text = await asyncio.to_thread(
                call_openai,
                api_key=settings.OPENAI_API_KEY,
                messages=messages,
                model=settings.OPENAI_MODEL,
                max_tokens=600,
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            if text and text.strip():
                break
        except AIClientError as exc:
            log.error("AI error drafting email | code=%s | error=%s | attempt=%d", exc.crv_code, exc, _attempt + 1)
            if _attempt == 1:
                raise HTTPException(status_code=502, detail="Could not draft email. Try again.")
        except Exception as exc:
            log.error("Unexpected error drafting email | error=%s | attempt=%d", exc, _attempt + 1)
            if _attempt == 1:
                raise HTTPException(status_code=502, detail="Drafting service error.")
    metrics.record_ai_response_time(round((time.perf_counter() - t0) * 1000))

    if not text or not text.strip():
        raise HTTPException(status_code=502, detail="AI returned an empty draft. Try again.")

    log.info("Draft email raw response | %s", text[:300])

    json_start = text.find("{")
    json_end = text.rfind("}") + 1
    try:
        parsed = json.loads(text[json_start:json_end] if json_start >= 0 else text)
    except (json.JSONDecodeError, ValueError):
        # Fallback: keep service usable even if model returns plain text.
        parsed = {"subject": "", "body": text.strip()}

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="Could not parse draft.")

    subject = str(parsed.get("subject", "")).strip()
    body = str(parsed.get("body", "")).strip()
    if not body:
        raise HTTPException(status_code=502, detail="AI returned an empty draft.")

    return DraftEmailResponse(
        to=job.contact_email or "",
        subject=subject or f"Application: {job.role} - {job.yacht}",
        body=body,
    )
