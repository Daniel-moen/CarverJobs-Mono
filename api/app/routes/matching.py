from __future__ import annotations

from pathlib import Path
import sys
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app import flags, metrics, schemas
from app.database import get_db
from app.error_codes import CRV_4001, CRV_4002
from app.logger import get_logger
from app.models import Job, User
from app.security import require_admin_session

_limiter = Limiter(key_func=get_remote_address)

log = get_logger("carver.matching")

# Add Matching Engine to import path (folder name contains a space).
ENGINE_DIR = Path(__file__).resolve().parents[2] / "Matching Engine"

router = APIRouter(prefix="/matching", tags=["matching"], dependencies=[Depends(require_admin_session)])

ENGINE_AVAILABLE = ENGINE_DIR.exists() and ENGINE_DIR.is_dir()
_ENGINE_IMPORT_ERROR: Optional[str] = None
if ENGINE_AVAILABLE:
    sys.path.insert(0, str(ENGINE_DIR))
    try:
        from config import Settings  # noqa: E402
        from models.job import JobPosting  # noqa: E402
        from models.user import UserProfile  # noqa: E402
        from queueing import MatchQueue  # noqa: E402
        from services.openai_client import OpenAIClient  # noqa: E402
        from services.matching_service import MatchingService  # noqa: E402
        from services.prompt_builder import PromptBuilder  # noqa: E402
        from utils.batching import FixedSizeBatchStrategy  # noqa: E402
    except Exception as exc:  # pragma: no cover
        ENGINE_AVAILABLE = False
        _ENGINE_IMPORT_ERROR = str(exc)

if ENGINE_AVAILABLE:
    _QUEUE: Optional[MatchQueue] = None

    def _build_queue() -> MatchQueue:
        settings = Settings()
        service = MatchingService(
            llm_client=OpenAIClient(api_key=settings.openai_api_key, model=settings.openai_model),
            batch_strategy=FixedSizeBatchStrategy(batch_size=settings.batch_size),
            prompt_builder=PromptBuilder(),
            verbose=settings.verbose,
        )
        return MatchQueue(
            matching_service=service,
            max_queue_size=settings.queue_max_size,
            worker_count=settings.queue_workers,
        )

    def _get_queue() -> MatchQueue:
        global _QUEUE
        if _QUEUE is None:
            _QUEUE = _build_queue()
        return _QUEUE

    def _to_user_profile(user: User) -> UserProfile:
        return UserProfile(
            user_id=str(user.id),
            desired_role=user.role or "",
            location=user.current_location or "Unknown",
            desired_pay_min=0.0,
            desired_length="Permanent",
            skills=[],
            certifications=[],
            years_experience=float(user.years_experience or 0),
        )

    def _to_job_posting(job: Job) -> JobPosting:
        pay = float(job.salary_max or job.salary_min or 0.0)
        return JobPosting(
            job_id=str(job.id),
            title=job.title,
            role=job.role or "",
            location=job.location,
            pay=pay,
            length=job.contract_type or "Unknown",
            description=job.description or "",
            required_skills=[],
            preferred_certifications=[],
        )

    @router.post("/enqueue", response_model=schemas.MatchingEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
    @_limiter.limit("10/minute")
    def enqueue_match(request: Request, payload: schemas.MatchingRequest, db: Session = Depends(get_db)):
        if not flags.is_enabled("matching"):
            metrics.increment("feature_blocked")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Job matching is temporarily disabled.")
        log.info("Enqueue request | user_id=%d | job_statuses=%s | limit=%d",
                 payload.user_id, payload.job_statuses, payload.job_limit)
        user = db.query(User).filter(User.id == payload.user_id, User.is_active.is_(True)).first()
        if not user:
            log.warning("Enqueue failed: user not found | user_id=%d", payload.user_id)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        jobs = (
            db.query(Job)
            .filter(Job.status.in_(payload.job_statuses))
            .order_by(Job.id.asc())
            .limit(payload.job_limit)
            .all()
        )
        if not jobs:
            log.warning("Enqueue failed: no jobs found | statuses=%s", payload.job_statuses)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching jobs found")

        queue = _get_queue()
        request_id = queue.enqueue(_to_user_profile(user), [_to_job_posting(job) for job in jobs])
        metrics.increment("matching_queued")
        log.info("Match job enqueued | request_id=%s | user_id=%d | jobs=%d",
                 request_id, payload.user_id, len(jobs))
        return schemas.MatchingEnqueueResponse(request_id=request_id, queued=True)

    @router.post("/run", response_model=schemas.MatchingRunResponse)
    @_limiter.limit("10/minute")
    def run_match(request: Request, payload: schemas.MatchingRequest, db: Session = Depends(get_db)):
        if not flags.is_enabled("matching"):
            metrics.increment("feature_blocked")
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Job matching is temporarily disabled.")
        log.info("Run request | user_id=%d | job_statuses=%s | limit=%d | timeout=%ss",
                 payload.user_id, payload.job_statuses, payload.job_limit, payload.timeout_seconds)
        user = db.query(User).filter(User.id == payload.user_id, User.is_active.is_(True)).first()
        if not user:
            log.warning("Run failed: user not found | user_id=%d", payload.user_id)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        jobs = (
            db.query(Job)
            .filter(Job.status.in_(payload.job_statuses))
            .order_by(Job.id.asc())
            .limit(payload.job_limit)
            .all()
        )
        if not jobs:
            log.warning("Run failed: no jobs found | statuses=%s", payload.job_statuses)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching jobs found")

        queue = _get_queue()
        request_id = queue.enqueue(_to_user_profile(user), [_to_job_posting(job) for job in jobs])
        log.info("Match submitted to queue | request_id=%s | user_id=%d | jobs=%d",
                 request_id, payload.user_id, len(jobs))
        result = queue.get_result(request_id, timeout=payload.timeout_seconds)
        if result is None:
            log.warning("Match result not found | request_id=%s", request_id)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
        if result.error:
            log.error("Match engine returned error | request_id=%s | error=%s", request_id, result.error)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Matching failed. Please try again.",
                headers={"X-Error-Code": CRV_4001},
            )
        metrics.increment("matching_completed")
        log.info("Match complete | request_id=%s | matches=%d", request_id, len(result.matches))
        return schemas.MatchingRunResponse(
            request_id=request_id,
            matches=[schemas.MatchResultItem(**m.__dict__) for m in result.matches],
        )
else:

    @router.post("/enqueue", response_model=schemas.MatchingEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
    @_limiter.limit("10/minute")
    def enqueue_match(request: Request, _payload: schemas.MatchingRequest):
        log.warning("Enqueue attempted but matching engine is unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Matching engine is not available.",
            headers={"X-Error-Code": CRV_4002},
        )

    @router.post("/run", response_model=schemas.MatchingRunResponse)
    @_limiter.limit("10/minute")
    def run_match(request: Request, _payload: schemas.MatchingRequest):
        log.warning("Run attempted but matching engine is unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Matching engine is not available.",
            headers={"X-Error-Code": CRV_4002},
        )
