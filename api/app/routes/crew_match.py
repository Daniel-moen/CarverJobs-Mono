import asyncio
import json
import queue
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app import metrics
from app.database import get_db
from app.logger import get_logger
from app.models import CrewProfile, Document, Job, JobDraftEvent, JobHistoryEntry, MatchSession, MatchSessionResult
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
from app.services.credits import add_credits, get_credit_balance, spend_credits
from app.services.matching_engine import (
    CandidateProfile,
    JobSummary,
    match_candidate_to_jobs,
)
from app.settings import settings

log = get_logger("carver.crew_match")
_limiter = Limiter(key_func=get_remote_address)
_background_match_tasks: set[asyncio.Task] = set()
MATCH_RUN_TIMEOUT_SECONDS = 600

router = APIRouter(prefix="/matching", tags=["crew-matching"])


# ── Mapping helpers ──────────────────────────────────────────────────────────

def _profile_to_candidate(
    p: CrewProfile,
    job_history: list[JobHistoryEntry] | None = None,
    document_summary: str = "",
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
        document_summary=document_summary,
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
        status=j.status or "open",
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


def _get_document_summary(db: Session, user_key: str) -> str:
    """Concatenate all scanned document texts for a user into one summary."""
    docs = (
        db.query(Document)
        .filter(Document.user_key == user_key, Document.scanned_text.isnot(None))
        .all()
    )
    if not docs:
        return ""
    parts = [f"[{d.doc_type.upper()}] {d.scanned_text}" for d in docs if d.scanned_text]
    return "\n\n".join(parts)


def _profile_summary(p: CrewProfile, job_history: list | None = None, document_summary: str = "") -> str:
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
    if document_summary:
        parts.append(f"Document insights:\n{document_summary[:500]}")
    return "\n".join(parts) if parts else "No profile details available."


def _delete_user_match_sessions(db: Session, user_key: str) -> int:
    """Remove prior website match sessions so restore always follows the latest run."""
    old_session_ids = [
        row[0]
        for row in (
            db.query(MatchSession.id)
            .filter(MatchSession.user_key == user_key)
            .all()
        )
    ]
    if not old_session_ids:
        return 0
    db.query(MatchSessionResult).filter(MatchSessionResult.session_id.in_(old_session_ids)).delete(synchronize_session=False)
    deleted = db.query(MatchSession).filter(MatchSession.id.in_(old_session_ids)).delete(synchronize_session=False)
    return deleted


def _as_aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _expire_stale_running_match_sessions(db: Session, user_key: str) -> int:
    """Mark abandoned running sessions as failed so the UI does not spin forever."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=MATCH_RUN_TIMEOUT_SECONDS)
    stale_sessions = (
        db.query(MatchSession)
        .filter(MatchSession.user_key == user_key, MatchSession.status == "running")
        .all()
    )
    expired = 0
    for s in stale_sessions:
        created_at = _as_aware_utc(s.created_at)
        if created_at and created_at > cutoff:
            continue
        s.status = "failed"
        expired += 1
        add_credits(db, user_key, amount=1)
    if expired:
        db.commit()
        log.warning("Expired %d stale match sessions | user=%s", expired, user_key)
    return expired


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
        current_credits = get_credit_balance(db, user_key)
        async def empty_stream():
            data = json.dumps({
                "session_id": 0,
                "matched": False,
                "total_jobs_scanned": 0,
                "total_matched": 0,
                "credits_remaining": current_credits,
                "matches": [],
            })
            yield f"event: complete\ndata: {data}\n\n"
        return StreamingResponse(empty_stream(), media_type="text/event-stream")

    credits_remaining = spend_credits(db, user_key, amount=1)
    if credits_remaining is None:
        raise HTTPException(
            status_code=402,
            detail="You're out of tokens. Top up to keep matching, or submit a job to earn a free token.",
        )
    deleted_sessions = _delete_user_match_sessions(db, user_key)
    if deleted_sessions:
        log.info("Deleted %d previous match sessions | user=%s", deleted_sessions, user_key)

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

    doc_summary = _get_document_summary(db, user_key)
    candidate = _profile_to_candidate(profile, job_history, document_summary=doc_summary)
    job_summaries = [_job_to_summary(j) for j in all_jobs]
    jobs_by_id = {j.id: j for j in all_jobs}
    total_job_count = len(all_jobs)

    log.info("Match session %d | user=%s | jobs=%d", session_id, user_key, total_job_count)

    progress_queue: queue.Queue[dict] = queue.Queue()
    result_queue: queue.Queue[dict] = queue.Queue()

    def on_progress(jobs_scanned: int, total_jobs: int, matches_so_far: int, batch_num: int, total_batches: int):
        progress_queue.put({
            "jobs_scanned": jobs_scanned,
            "total_jobs": total_jobs,
            "matches_so_far": matches_so_far,
            "batch": batch_num,
            "total_batches": total_batches,
        })

    async def run_match_job():
        from app.database import SessionLocal

        t0 = time.perf_counter()
        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(
                    match_candidate_to_jobs,
                    api_key=settings.OPENAI_API_KEY,
                    model=settings.OPENAI_MODEL,
                    candidate=candidate,
                    jobs=job_summaries,
                    on_progress=on_progress,
                ),
                timeout=MATCH_RUN_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            result_db = SessionLocal()
            try:
                s = result_db.query(MatchSession).get(session_id)
                if s:
                    s.status = "failed"
                add_credits(result_db, user_key, amount=1)
                result_db.commit()
            finally:
                result_db.close()
            log.error("Match session %d failed | user=%s | %s", session_id, user_key, exc)
            result_queue.put({
                "event": "error",
                "data": {"detail": "Matching failed. Please try again."},
            })
            return
        finally:
            metrics.record_ai_response_time(round((time.perf_counter() - t0) * 1000))

        matched_results = [r for r in results if r.matched]

        result_db = SessionLocal()
        try:
            s = result_db.query(MatchSession).get(session_id)
            if not s:
                log.info("Match session %d was superseded before results persisted | user=%s", session_id, user_key)
                result_queue.put({
                    "event": "error",
                    "data": {"detail": "A newer match run was started."},
                })
                return
            for r in matched_results:
                result_db.add(MatchSessionResult(
                    session_id=session_id,
                    job_id=r.job_id,
                    matched=r.matched,
                    compatibility=r.compatibility,
                    reason=r.reason,
                    strengths=json.dumps(r.strengths),
                    gaps=json.dumps(r.gaps),
                    factor_scores=json.dumps(r.factor_scores),
                ))
            s.status = "completed"
            s.total_matched = len(matched_results)
            s.completed_at = datetime.now(timezone.utc)
            result_db.commit()
        except Exception:
            log.exception("Failed to persist match session %d results", session_id)
            result_db.rollback()
            try:
                s = result_db.query(MatchSession).get(session_id)
                if s:
                    s.status = "failed"
                add_credits(result_db, user_key, amount=1)
                result_db.commit()
            except Exception:
                log.exception("Failed to mark match session %d as failed", session_id)
                result_db.rollback()
            result_queue.put({
                "event": "error",
                "data": {"detail": "Matching finished but results could not be saved. Please try again."},
            })
            return
        finally:
            result_db.close()

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
            credits_remaining=credits_remaining,
            matches=response_matches,
        )
        result_queue.put({
            "event": "complete",
            "data": final.model_dump_json(),
            "raw_json": True,
        })

    match_job = asyncio.create_task(run_match_job())
    _background_match_tasks.add(match_job)
    match_job.add_done_callback(_background_match_tasks.discard)

    async def event_stream():
        from app.services.matching_engine import BATCH_SIZE

        _total_batches = (total_job_count + BATCH_SIZE - 1) // BATCH_SIZE
        yield f"event: progress\ndata: {json.dumps({'session_id': session_id, 'jobs_scanned': 0, 'total_jobs': total_job_count, 'matches_so_far': 0, 'batch': 0, 'total_batches': _total_batches})}\n\n"

        last_ping = time.perf_counter()
        try:
            while True:
                await asyncio.sleep(0.5)
                sent_something = False

                while not progress_queue.empty():
                    try:
                        evt = progress_queue.get_nowait()
                        evt["session_id"] = session_id
                        yield f"event: progress\ndata: {json.dumps(evt)}\n\n"
                        sent_something = True
                        last_ping = time.perf_counter()
                    except queue.Empty:
                        break

                while not result_queue.empty():
                    try:
                        evt = result_queue.get_nowait()
                    except queue.Empty:
                        break
                    event_name = evt.get("event", "message")
                    data = evt.get("data", {})
                    if evt.get("raw_json"):
                        payload = data
                    else:
                        payload = json.dumps(data)
                    yield f"event: {event_name}\ndata: {payload}\n\n"
                    return

                if match_job.done() and result_queue.empty():
                    yield f"event: error\ndata: {json.dumps({'detail': 'Matching finished unexpectedly. Please refresh and try again.'})}\n\n"
                    return

                if not sent_something and (time.perf_counter() - last_ping) > 8:
                    yield ": keepalive\n\n"
                    last_ping = time.perf_counter()
        except asyncio.CancelledError:
            log.info("Match session %d stream disconnected | user=%s", session_id, user_key)
            raise

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
    _expire_stale_running_match_sessions(db, user_key)
    sessions = (
        db.query(MatchSession)
        .filter(MatchSession.user_key == user_key)
        .order_by(MatchSession.id.desc())
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
    if match_session.status == "running":
        created_at = _as_aware_utc(match_session.created_at)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=MATCH_RUN_TIMEOUT_SECONDS)
        if not created_at or created_at <= cutoff:
            match_session.status = "failed"
            add_credits(db, user_key, amount=1)
            db.commit()
            db.refresh(match_session)

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
            log.warning("Corrupt strengths JSON | session=%d | job=%d", session_id, r.job_id)
        try:
            gaps = json.loads(r.gaps) if r.gaps else []
        except json.JSONDecodeError:
            log.warning("Corrupt gaps JSON | session=%d | job=%d", session_id, r.job_id)
        try:
            factor_scores = json.loads(r.factor_scores) if r.factor_scores else {}
        except json.JSONDecodeError:
            log.warning("Corrupt factor_scores JSON | session=%d | job=%d", session_id, r.job_id)

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

def build_draft_email_system_prompt(profile_text: str, first_name: str, job: Job, profile_url: str) -> str:
    """Shared ghost-writer prompt — used by the web draft endpoint and the WhatsApp bot."""
    return f"""You ghost-write job application emails for yacht crew. The email must sound like a real person wrote it — professional but natural. Not a cover letter, not a text message. Think: a well-spoken crew member writing a proper email, but without corporate stiffness.

TONE:
- Professional and direct. Polite but not stiff.
- Natural language — contractions are fine, vary sentence length, avoid robotic patterns.
- Confident and to the point. No overselling or grovelling.
- The reader should not be able to tell AI wrote this.

STRUCTURE (4-5 sentences total, keep it tight):
1. Open naturally — mention the specific role and yacht name. Don't use a template-sounding opener.
2. Briefly mention the most relevant experience for THIS role (recent yacht + position). Only mention a cert if the job listing specifically requires it.
3. Include the profile link naturally — e.g. "You can find my full profile here: [link]"
4. Short professional sign-off, then: {first_name}

BANNED — instant AI tells:
- "I'm interested in the [Role] position on your [Yacht]" (template opener — rephrase naturally each time)
- "align well with your needs/requirements"
- "I am confident that", "I believe I would be a great fit"
- "I am excited to", "passionate about", "eager to"
- "I am writing to express my interest"
- "My [X] skills and [Y] align with"
- Listing multiple certifications in a row
- Mentioning salary, location preferences, contract preferences, nationality
- Any sentence that reads like a LinkedIn summary

Vary the opening and structure between drafts — don't use the same formula every time.

Crew profile:
{profile_text}

Job:
Role: {job.role}
Yacht: {job.yacht}
{('Description: ' + (job.description or '')[:400]) if job.description else ''}
{('Requirements: ' + (job.requirements or '')[:300]) if job.requirements else ''}
{('Profile link: ' + profile_url) if profile_url else 'No profile link available.'}

Respond with JSON only:
{{"subject": "...", "body": "..."}}"""


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

    doc_summary = _get_document_summary(db, user_key)
    profile_text = _profile_summary(profile, job_history, document_summary=doc_summary)

    system_prompt = build_draft_email_system_prompt(profile_text, first_name, job, profile_url)

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
                model=settings.EMAIL_AI_MODEL,
                max_tokens=400,
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

    # Record engagement signal so the agency dashboard can show how many crew
    # have drafted an email for this job. Unique on (job_id, user_key) so
    # repeated drafts by the same crew member don't inflate the counter.
    try:
        existing = (
            db.query(JobDraftEvent)
            .filter(JobDraftEvent.job_id == job.id, JobDraftEvent.user_key == user_key)
            .first()
        )
        if existing is None:
            db.add(JobDraftEvent(job_id=job.id, user_key=user_key))
            db.commit()
    except Exception as exc:  # noqa: BLE001 — never block drafting on telemetry
        db.rollback()
        log.warning("Failed to record JobDraftEvent | job_id=%s | error=%s", job.id, exc)

    return DraftEmailResponse(
        to=job.contact_email or "",
        subject=subject or f"Application: {job.role} - {job.yacht}",
        body=body,
    )
